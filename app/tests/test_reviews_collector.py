from datetime import UTC, datetime, timedelta

from catalog.models import Game, GamePlatform, SourceFetch
from django.test import TestCase
from metacritic.dto import FetchEvidence, ReviewPageDTO, ReviewRecordDTO
from processing.models import DailyCandidate, DailyCycle
from reviews import collector
from reviews.models import Review, ReviewCollectionJob, ReviewObservation
from summaries.models import SummaryJob


class FakeClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now_utc(self) -> datetime:
        return self.instant


def _evidence(outcome: str = "succeeded", error_code: str | None = None) -> FetchEvidence:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    return FetchEvidence(
        kind="review_page",
        url="https://backend.metacritic.com/reviews/x",
        started_at=now,
        completed_at=now,
        http_status=200 if outcome == "succeeded" else None,
        response_sha256="a" * 64 if outcome == "succeeded" else None,
        parser_contract_version="1.0.0",
        outcome=outcome,
        error_code=error_code,
    )


def _item(n: int, *, source_review_id: str | None = None) -> ReviewRecordDTO:
    return ReviewRecordDTO(
        source_review_id=source_review_id,
        author_or_source_label=f"author{n}",
        score_label="8",
        date_label="2026-01-01",
        text=f"Review text number {n}.",
        external_url=f"https://example.com/{n}",
    )


class FakeGateway:
    def __init__(self, pages_by_cursor: dict[str | None, ReviewPageDTO | None]) -> None:
        self.pages_by_cursor = pages_by_cursor
        self.calls: list[str | None] = []

    def fetch_review_page(
        self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
    ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
        self.calls.append(cursor)
        page = self.pages_by_cursor.get(cursor)
        outcome = "succeeded" if page is not None else "failed"
        error_code = None if page is not None else "http_500"
        return page, _evidence(outcome, error_code)


def _make_job(audience: str = "critic") -> ReviewCollectionJob:
    game = Game.objects.create(source_game_id="g1", canonical_locator="/game/g1/", title="Game 1")
    platform = GamePlatform.objects.create(
        game=game,
        source_platform_id="p1",
        source_game_platform_id="gp1",
        slug="pc",
        name="PC",
        critic_reviews_path="/game/g1/critic-reviews/?platform=pc",
        user_reviews_path="/game/g1/user-reviews/?platform=pc",
    )
    cycle = DailyCycle.objects.create(business_date="2026-09-12")
    candidate = DailyCandidate.objects.create(
        cycle=cycle, game=game, source_order=1, state="processed"
    )
    return ReviewCollectionJob.objects.create(
        daily_candidate=candidate, game_platform=platform, audience=audience
    )


class ClaimNextJobTests(TestCase):
    def test_claims_a_pending_job_and_bumps_the_fencing_token(self) -> None:
        job = _make_job()
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = collector.claim_next_job(clock)
        assert claimed is not None
        self.assertEqual(claimed.id, job.id)
        self.assertEqual(claimed.state, "running")
        self.assertEqual(claimed.fencing_token, 1)

    def test_returns_none_when_nothing_is_due(self) -> None:
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        self.assertIsNone(collector.claim_next_job(clock))

    def test_a_job_left_running_by_a_crash_is_reclaimed_once_its_lease_expires(self) -> None:
        # A crashed/killed worker never calls collect_one_page again, so the job is stuck in
        # "running" with the fencing token it was claimed under. Nothing but a fresh claim past
        # the lease TTL should ever make that row claimable again.
        job = _make_job()
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        first = collector.claim_next_job(clock)
        assert first is not None
        self.assertEqual(first.fencing_token, 1)

        # Not yet expired: still stuck, as expected.
        clock.instant += collector.LEASE_TTL - timedelta(seconds=1)
        self.assertIsNone(collector.claim_next_job(clock))

        # Past the lease TTL: recovered and reclaimed with a bumped fencing token, invalidating
        # any late write the dead worker might still attempt with token 1.
        clock.instant += timedelta(seconds=2)
        reclaimed = collector.claim_next_job(clock)
        assert reclaimed is not None
        self.assertEqual(reclaimed.id, job.id)
        self.assertEqual(reclaimed.state, "running")
        self.assertEqual(reclaimed.fencing_token, 3)  # 1 (first claim) + 1 (recovery) + 1 (reclaim)

    def test_a_late_page_from_a_recovered_job_does_not_commit(self) -> None:
        job = _make_job()
        page = ReviewPageDTO(items=(_item(1),), reported_total=1, next_cursor=None)
        gateway = FakeGateway({None: page})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        stale = collector.claim_next_job(clock)
        assert stale is not None

        # The lease expires without collect_one_page ever being called again (a real crash).
        clock.instant += collector.LEASE_TTL + timedelta(seconds=1)
        collector.claim_next_job(clock)  # a second worker recovers and reclaims the row

        # The first (now stale) worker finally gets around to processing its old claim.
        result = collector.collect_one_page(gateway, clock, stale)

        self.assertEqual(Review.objects.count(), 0)
        self.assertEqual(SourceFetch.objects.filter(kind="review_page").count(), 0)
        current = ReviewCollectionJob.objects.get(pk=job.id)
        self.assertNotEqual(current.state, "complete")
        self.assertEqual(result.id, stale.id)


class CompleteRouteTests(TestCase):
    def test_a_single_page_route_reaches_complete(self) -> None:
        _make_job()
        page = ReviewPageDTO(
            items=(_item(1), _item(2), _item(3)), reported_total=3, next_cursor=None
        )
        gateway = FakeGateway({None: page})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = collector.claim_next_job(clock)
        assert claimed is not None

        updated = collector.collect_one_page(gateway, clock, claimed)

        self.assertEqual(updated.state, "complete")
        self.assertEqual(updated.unique_count, 3)
        self.assertEqual(updated.fetched_count, 3)
        self.assertEqual(Review.objects.count(), 3)
        self.assertEqual(ReviewObservation.objects.count(), 3)
        self.assertEqual(SourceFetch.objects.filter(kind="review_page").count(), 1)

    def test_a_multi_page_route_advances_the_cursor_and_reaches_complete(self) -> None:
        _make_job()
        page1 = ReviewPageDTO(items=(_item(1), _item(2)), reported_total=3, next_cursor="cursor-2")
        page2 = ReviewPageDTO(items=(_item(3),), reported_total=3, next_cursor=None)
        gateway = FakeGateway({None: page1, "cursor-2": page2})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        claimed = collector.claim_next_job(clock)
        assert claimed is not None
        first = collector.collect_one_page(gateway, clock, claimed)
        self.assertEqual(first.state, "pending")
        self.assertEqual(first.next_cursor, "cursor-2")

        reclaimed = collector.claim_next_job(clock)
        assert reclaimed is not None
        second = collector.collect_one_page(gateway, clock, reclaimed)

        self.assertEqual(second.state, "complete")
        self.assertEqual(second.page_count, 2)
        self.assertEqual(Review.objects.count(), 3)


class EmptyRouteTests(TestCase):
    def test_a_valid_zero_total_is_empty_not_unstable(self) -> None:
        _make_job()
        page = ReviewPageDTO(items=(), reported_total=0, next_cursor=None)
        gateway = FakeGateway({None: page})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = collector.claim_next_job(clock)
        assert claimed is not None

        updated = collector.collect_one_page(gateway, clock, claimed)
        self.assertEqual(updated.state, "empty")


class UnstableRouteTests(TestCase):
    def test_a_repeated_page_identity_is_unstable(self) -> None:
        _make_job()
        page = ReviewPageDTO(items=(_item(1), _item(2)), reported_total=5, next_cursor="loop")
        gateway = FakeGateway({None: page, "loop": page})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        claimed = collector.claim_next_job(clock)
        assert claimed is not None
        first = collector.collect_one_page(gateway, clock, claimed)
        self.assertEqual(first.state, "pending")

        reclaimed = collector.claim_next_job(clock)
        assert reclaimed is not None
        second = collector.collect_one_page(gateway, clock, reclaimed)
        self.assertEqual(second.state, "unstable")
        self.assertEqual(second.last_error, "repeated_page_identity")

    def test_a_changed_reported_total_mid_route_is_unstable(self) -> None:
        _make_job()
        page1 = ReviewPageDTO(items=(_item(1),), reported_total=5, next_cursor="p2")
        page2 = ReviewPageDTO(items=(_item(2),), reported_total=9, next_cursor=None)
        gateway = FakeGateway({None: page1, "p2": page2})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        claimed = collector.claim_next_job(clock)
        assert claimed is not None
        collector.collect_one_page(gateway, clock, claimed)
        reclaimed = collector.claim_next_job(clock)
        assert reclaimed is not None
        updated = collector.collect_one_page(gateway, clock, reclaimed)

        self.assertEqual(updated.state, "unstable")
        self.assertEqual(updated.last_error, "total_results_changed")


class RetryableFailureTests(TestCase):
    def test_a_transport_failure_is_retryable_with_backoff(self) -> None:
        _make_job()
        gateway = FakeGateway({})  # every cursor "fails"
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = collector.claim_next_job(clock)
        assert claimed is not None

        updated = collector.collect_one_page(gateway, clock, claimed)

        self.assertEqual(updated.state, "retryable")
        self.assertIsNotNone(updated.available_at)
        self.assertEqual(updated.attempt_count, 1)

    def test_exhausting_automatic_attempts_fails_the_job(self) -> None:
        job = _make_job()
        gateway = FakeGateway({})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))

        current = job
        for _ in range(collector.MAX_AUTOMATIC_ATTEMPTS):
            claimed = collector.claim_next_job(clock)
            assert claimed is not None
            current = collector.collect_one_page(gateway, clock, claimed)
            clock.instant += collector.BACKOFF_STEPS[-1] + collector.BACKOFF_STEPS[-1]

        self.assertEqual(current.state, "failed")
        self.assertEqual(current.attempt_count, collector.MAX_AUTOMATIC_ATTEMPTS)


class IdempotentRedeliveryTests(TestCase):
    def test_reprocessing_the_same_accepted_page_does_not_duplicate_observations(self) -> None:
        # A durable-worker crash-recovery scenario: the same page is handed to collect_one_page
        # twice for the same job/generation (e.g. a redelivered claim). get_or_create on the
        # (job, generation, review) key must not create duplicate observations.
        _make_job()
        page = ReviewPageDTO(items=(_item(1), _item(2)), reported_total=2, next_cursor=None)
        gateway = FakeGateway({None: page})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = collector.claim_next_job(clock)
        assert claimed is not None
        collector.collect_one_page(gateway, clock, claimed)

        self.assertEqual(ReviewObservation.objects.count(), 2)
        self.assertEqual(Review.objects.count(), 2)


class LeaseLostMidCollectionTests(TestCase):
    def test_a_reclaimed_job_is_not_overwritten_by_the_stale_worker(self) -> None:
        job = _make_job()
        page = ReviewPageDTO(items=(_item(1),), reported_total=1, next_cursor=None)

        class ReclaimingGateway(FakeGateway):
            def fetch_review_page(
                self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
            ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
                stale = ReviewCollectionJob.objects.get(pk=job.id)
                stale.fencing_token += 1
                stale.state = "pending"
                stale.save(update_fields=["fencing_token", "state"])
                return super().fetch_review_page(audience, game_slug, platform_slug, cursor)

        gateway = ReclaimingGateway({None: page})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = collector.claim_next_job(clock)
        assert claimed is not None

        collector.collect_one_page(gateway, clock, claimed)

        self.assertEqual(Review.objects.count(), 0)
        self.assertEqual(SourceFetch.objects.get(kind="review_page").outcome, "superseded")
        current = ReviewCollectionJob.objects.get(pk=job.id)
        self.assertEqual(current.state, "pending")


class CorpusAndSummaryJobTriggerTests(TestCase):
    def test_completing_the_only_known_route_builds_a_corpus_and_summary_job(self) -> None:
        job = _make_job(audience="critic")
        page = ReviewPageDTO(
            items=(_item(1), _item(2), _item(3)), reported_total=3, next_cursor=None
        )
        gateway = FakeGateway({None: page})
        clock = FakeClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
        claimed = collector.claim_next_job(clock)
        assert claimed is not None

        collector.collect_one_page(gateway, clock, claimed)

        self.assertEqual(
            SummaryJob.objects.filter(game=job.game_platform.game, audience="critic").count(), 1
        )
