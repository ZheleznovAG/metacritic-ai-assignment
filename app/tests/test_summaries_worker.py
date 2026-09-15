import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
from catalog.models import Game, GamePlatform
from django.test import TestCase, TransactionTestCase
from reviews.models import Review, ReviewCorpus, ReviewCorpusItem
from reviews.versioning import version_fingerprint
from summaries import contour, worker
from summaries.models import SummaryAttempt, SummaryJob

from tests.concurrency import run_concurrently


class FakeClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now_utc(self) -> datetime:
        return self.instant


def _make_game(n: int) -> Game:
    return Game.objects.create(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=f"Game {n}"
    )


def _make_platform(game: Game, n: int = 1) -> GamePlatform:
    return GamePlatform.objects.create(
        game=game,
        source_platform_id=f"p{n}",
        source_game_platform_id=f"gp-{game.id}-{n}",
        slug="pc",
        name="PC",
    )


def _make_review(platform: GamePlatform, audience: str, n: int) -> Review:
    return Review.objects.create(
        game_platform=platform,
        audience=audience,
        identity_key=f"id:{n}",
        text_original=f"Review text number {n} with real content.",
        content_sha256=f"sha{n}",
        version_sha256=version_fingerprint(
            f"Review text number {n} with real content.", None, None, None
        ),
        first_seen_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def _make_corpus(
    game: Game, audience: str, reviews: list[Review], *, unique_count: int | None = None
) -> ReviewCorpus:
    review_key = "-".join(str(review.id) for review in reviews)
    corpus = ReviewCorpus.objects.create(
        game=game,
        audience=audience,
        policy_version="1.0.0-candidate",
        source_set_fingerprint=hashlib.sha256(
            f"fp-{game.id}-{audience}-{review_key}".encode()
        ).hexdigest(),
        model_input_fingerprint=hashlib.sha256(
            f"input-{game.id}-{audience}-{review_key}".encode()
        ).hexdigest(),
        complete_route_count=1,
        empty_route_count=0,
        reported_count=len(reviews),
        fetched_count=len(reviews),
        unique_count=unique_count if unique_count is not None else len(reviews),
        deduplicated_count=0,
        selected_count=len(reviews),
        tokenizer_id="o200k_harmony",
        tokenizer_version="0.14.0",
        raw_prompt_tokens=100,
        guarded_prompt_tokens=164,
        completion_reservation=800,
    )
    for ordinal, review in enumerate(reviews, start=1):
        ReviewCorpusItem.objects.create(
            corpus=corpus,
            ordinal=ordinal,
            prompt_review_id=f"R{ordinal:02d}",
            review=review,
            input_text=review.text_original,
            input_token_count=10,
            sha256=f"itemsha{ordinal}",
            was_truncated=False,
        )
    return corpus


def _ok_response(
    correlation_id: str,
    audience: str,
    likes: list[dict[str, object]] | None = None,
    dislikes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "model": contour.REQUESTED_MODEL,
        "system_fingerprint": "fp_test",
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "case_id": correlation_id,
                            "audience": audience,
                            "status": "ok",
                            "likes": likes
                            if likes is not None
                            else [{"claim": "Great combat.", "support": ["R01"]}],
                            "dislikes": dislikes if dislikes is not None else [],
                            "insufficient_data_reason": None,
                        }
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


class StaleLeaseRecoveryTests(TestCase):
    def test_a_job_left_running_by_a_crash_is_reclaimed_once_its_lease_expires(self) -> None:
        game = _make_game(9)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "critic", i) for i in range(3)]
        corpus = _make_corpus(game, "critic", reviews)
        job = worker.ensure_job(corpus)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        first = worker.claim_next_job(clock)
        assert first is not None
        self.assertEqual(first.fencing_token, 1)

        clock.instant += worker.LEASE_TTL - timedelta(seconds=1)
        self.assertIsNone(worker.claim_next_job(clock))

        clock.instant += timedelta(seconds=2)
        reclaimed = worker.claim_next_job(clock)
        assert reclaimed is not None
        self.assertEqual(reclaimed.id, job.id)
        self.assertEqual(reclaimed.fencing_token, 3)  # 1 (first claim) + 1 (recovery) + 1 (reclaim)


class ColdSetTests(TestCase):
    def test_a_fresh_job_with_a_real_provider_response_succeeds(self) -> None:
        game = _make_game(1)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "critic", i) for i in range(3)]
        corpus = _make_corpus(game, "critic", reviews)
        job = worker.ensure_job(corpus)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = worker.claim_next_job(clock)
        assert claimed is not None

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            correlation_id = json.loads(body["messages"][1]["content"])["case_id"]
            return httpx.Response(200, json=_ok_response(correlation_id, "critic"))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        updated = worker.process_job(
            client, clock, claimed, api_key="test-key", base_url="https://api.groq.com/openai/v1"
        )

        self.assertEqual(updated.state, "succeeded")
        summary = updated.summary
        self.assertEqual(summary.status, "ok")
        self.assertEqual(summary.claims.count(), 1)
        self.assertEqual(SummaryAttempt.objects.filter(job=job).count(), 1)
        attempt = SummaryAttempt.objects.get(job=job)
        self.assertEqual(attempt.outcome, "succeeded")
        self.assertEqual(attempt.actual_total_tokens, 120)


class UnchangedRepeatTests(TestCase):
    def test_same_corpus_and_contour_is_a_cache_hit_not_a_new_job(self) -> None:
        game = _make_game(2)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "user", i) for i in range(3)]
        corpus = _make_corpus(game, "user", reviews)
        first = worker.ensure_job(corpus)
        second = worker.ensure_job(corpus)
        self.assertEqual(first.id, second.id)
        self.assertEqual(SummaryJob.objects.filter(game=game, audience="user").count(), 1)


class ChangedInputStreamTests(TestCase):
    def test_a_different_source_set_creates_an_independent_job(self) -> None:
        game = _make_game(3)
        platform = _make_platform(game)
        reviews_a = [_make_review(platform, "user", i) for i in range(3)]
        corpus_a = _make_corpus(game, "user", reviews_a)
        job_a = worker.ensure_job(corpus_a)

        reviews_b = [_make_review(platform, "user", i) for i in range(3, 6)]
        corpus_b = _make_corpus(game, "user", reviews_b)
        job_b = worker.ensure_job(corpus_b)

        self.assertNotEqual(job_a.id, job_b.id)
        self.assertEqual(SummaryJob.objects.filter(game=game, audience="user").count(), 2)


class QuotaExhaustionTests(TestCase):
    def test_insufficient_headroom_defers_without_a_provider_call(self) -> None:
        game = _make_game(4)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "critic", i) for i in range(3)]
        corpus = _make_corpus(game, "critic", reviews)
        job = worker.ensure_job(corpus)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        # Simulate near-exhausted minute budget via a committed attempt for an unrelated job.
        other_reviews = [_make_review(platform, "critic", 100 + i) for i in range(3)]
        other_corpus = _make_corpus(game, "critic", other_reviews)
        other_job = worker.ensure_job(other_corpus)
        SummaryAttempt.objects.create(
            job=other_job,
            attempt_no=1,
            provider="groq",
            api_kind="chat_completions",
            requested_model=contour.REQUESTED_MODEL,
            contour_versions=contour.contour_versions(),
            generation_params=contour.GENERATION_PARAMS,
            estimated_prompt_tokens=6800,
            reserved_total_tokens=6800,
            started_at=clock.now_utc(),
        )

        claimed = worker.claim_next_job(clock)
        assert claimed is not None
        self.assertEqual(claimed.id, job.id)

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no provider call should happen when quota is exhausted")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        updated = worker.process_job(
            client, clock, claimed, api_key="test-key", base_url="https://api.groq.com/openai/v1"
        )

        self.assertEqual(updated.state, "delayed_capacity")
        self.assertEqual(updated.last_error, "quota_exhausted")
        self.assertIsNotNone(updated.available_at)
        self.assertEqual(SummaryAttempt.objects.filter(job=job).count(), 0)


class RateLimitedTests(TestCase):
    def test_a_429_response_sets_delayed_capacity_not_failed(self) -> None:
        game = _make_game(5)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "user", i) for i in range(3)]
        corpus = _make_corpus(game, "user", reviews)
        worker.ensure_job(corpus)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = worker.claim_next_job(clock)
        assert claimed is not None

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        updated = worker.process_job(
            client, clock, claimed, api_key="test-key", base_url="https://api.groq.com/openai/v1"
        )

        self.assertEqual(updated.state, "delayed_capacity")
        self.assertIsNotNone(updated.available_at)
        attempt = SummaryAttempt.objects.get(job=updated)
        self.assertEqual(attempt.outcome, "delayed_capacity")


class MalformedOutputTests(TestCase):
    def test_schema_invalid_output_is_retryable_and_keeps_no_summary(self) -> None:
        game = _make_game(6)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "critic", i) for i in range(3)]
        corpus = _make_corpus(game, "critic", reviews)
        worker.ensure_job(corpus)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = worker.claim_next_job(clock)
        assert claimed is not None

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "model": contour.REQUESTED_MODEL,
                    "choices": [{"message": {"content": json.dumps({"status": "ok"})}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        updated = worker.process_job(
            client, clock, claimed, api_key="test-key", base_url="https://api.groq.com/openai/v1"
        )

        self.assertEqual(updated.state, "retryable")
        self.assertFalse(hasattr(updated, "summary"))


class InsufficientDataTests(TestCase):
    def test_fewer_than_three_reviews_skips_the_provider_entirely(self) -> None:
        game = _make_game(7)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "user", 1)]
        corpus = _make_corpus(game, "user", reviews, unique_count=1)
        worker.ensure_job(corpus)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = worker.claim_next_job(clock)
        assert claimed is not None

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no provider call should happen below the meaningful-review floor")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        updated = worker.process_job(
            client, clock, claimed, api_key="test-key", base_url="https://api.groq.com/openai/v1"
        )

        self.assertEqual(updated.state, "insufficient_data")
        self.assertEqual(updated.summary.status, "insufficient_data")
        self.assertEqual(updated.summary.insufficient_reason, "not_enough_meaningful_reviews")


class LeaseLostMidAttemptTests(TestCase):
    def test_a_reclaimed_job_does_not_get_overwritten_by_the_stale_worker(self) -> None:
        game = _make_game(8)
        platform = _make_platform(game)
        reviews = [_make_review(platform, "critic", i) for i in range(3)]
        corpus = _make_corpus(game, "critic", reviews)
        worker.ensure_job(corpus)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = worker.claim_next_job(clock)
        assert claimed is not None

        def handler(request: httpx.Request) -> httpx.Response:
            # Simulate another worker reclaiming the lease mid-flight (e.g. after a crash).
            stale = SummaryJob.objects.get(pk=claimed.id)
            stale.fencing_token += 1
            stale.state = "pending"
            stale.save(update_fields=["fencing_token", "state"])
            body = json.loads(request.content)
            correlation_id = json.loads(body["messages"][1]["content"])["case_id"]
            return httpx.Response(200, json=_ok_response(correlation_id, "critic"))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        result = worker.process_job(
            client, clock, claimed, api_key="test-key", base_url="https://api.groq.com/openai/v1"
        )

        # The stale attempt must not commit a summary; the reclaiming worker's own state stands.
        self.assertFalse(hasattr(result, "summary"))
        current = SummaryJob.objects.get(pk=claimed.id)
        self.assertEqual(current.state, "pending")


class ClaimNextJobRaceTests(TransactionTestCase):
    """HRD-03: mirrors `tests.test_reviews_collector.ClaimNextJobRaceTests` for the summaries
    queue. The sequential/`FakeClock` tests above (e.g. `StaleLeaseRecoveryTests`) prove the
    reclaim logic is correct given a known interleaving on one connection; they cannot prove
    `select_for_update(skip_locked=True)` actually serializes two genuinely concurrent
    PostgreSQL claimants, since `TestCase` wraps each test in a single transaction. These use
    real threads with their own DB connections, synchronized with a `threading.Barrier`."""

    def _job_for(self, n: int) -> SummaryJob:
        game = _make_game(n)
        platform = _make_platform(game, n)
        reviews = [_make_review(platform, "critic", n * 10 + i) for i in range(3)]
        corpus = _make_corpus(game, "critic", reviews)
        return worker.ensure_job(corpus)

    def test_two_real_threads_racing_for_one_job_never_both_claim_it(self) -> None:
        job = self._job_for(1)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        def claim() -> SummaryJob | None:
            return worker.claim_next_job(clock)

        claims, errors = run_concurrently(claim, claim)

        self.assertEqual(errors, [], f"claim_next_job raised under real concurrency: {errors}")
        winners = [claim for claim in claims if claim is not None]
        self.assertEqual(len(winners), 1, f"exactly one racer must claim the job, got {claims}")
        self.assertEqual(winners[0].id, job.id)
        self.assertEqual(winners[0].fencing_token, 1)
        current = SummaryJob.objects.get(pk=job.id)
        self.assertEqual((current.state, current.fencing_token), ("running", 1))

    def test_two_real_threads_with_two_jobs_each_claim_a_different_one(self) -> None:
        first = self._job_for(2)
        second = self._job_for(3)
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        def claim() -> SummaryJob | None:
            return worker.claim_next_job(clock)

        claims, errors = run_concurrently(claim, claim)

        self.assertEqual(errors, [])
        assert claims[0] is not None and claims[1] is not None
        self.assertEqual({claims[0].id, claims[1].id}, {first.id, second.id})
        self.assertEqual(
            SummaryJob.objects.filter(state="running").count(), 2, "no lost/duplicate claim"
        )
