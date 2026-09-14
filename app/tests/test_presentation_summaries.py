from datetime import UTC, datetime, timedelta

from catalog.models import Game, GamePlatform
from django.test import TestCase
from presentation.summaries import get_summaries
from processing.models import DailyCandidate, DailyCycle
from reviews.models import (
    Review,
    ReviewCollectionJob,
    ReviewCorpus,
    ReviewCorpusHead,
    ReviewCorpusItem,
)
from reviews.snapshots import collection_state
from reviews.versioning import version_fingerprint
from summaries.contour import contour_fingerprint
from summaries.models import ReviewSummary, SummaryClaim, SummaryJob


def _make_game(n: int) -> Game:
    return Game.objects.create(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=f"Game {n}"
    )


def _make_corpus_item(corpus: ReviewCorpus, tag: str) -> ReviewCorpusItem:
    platform = GamePlatform.objects.create(
        game=corpus.game,
        source_platform_id=f"p-{tag}",
        source_game_platform_id=f"gp-{tag}",
        slug="pc",
        name="PC",
    )
    review = Review.objects.create(
        game_platform=platform,
        audience=corpus.audience,
        identity_key=f"id:{tag}",
        text_original="Some review text.",
        content_sha256=f"sha-{tag}",
        version_sha256=version_fingerprint("Some review text.", None, None, None),
        first_seen_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    return ReviewCorpusItem.objects.create(
        corpus=corpus,
        ordinal=1,
        prompt_review_id="R01",
        review=review,
        input_text=review.text_original,
        input_token_count=5,
        sha256="itemsha",
        was_truncated=False,
    )


def _make_corpus(game: Game, audience: str, tag: str) -> ReviewCorpus:
    corpus = ReviewCorpus.objects.create(
        game=game,
        audience=audience,
        policy_version="1.0.0-candidate",
        source_set_fingerprint=f"fp-{tag}",
        model_input_fingerprint=f"input-{tag}",
        complete_route_count=1,
        empty_route_count=0,
        reported_count=10,
        fetched_count=10,
        unique_count=10,
        deduplicated_count=0,
        selected_count=5,
        tokenizer_id="o200k_harmony",
        tokenizer_version="0.14.0",
        raw_prompt_tokens=100,
        guarded_prompt_tokens=164,
        completion_reservation=800,
    )
    # This presentation fixture supplies the verified-head contract. Builder correctness is
    # tested through real observations in test_summary_freshness/test_reviews_snapshots.
    route, _ = GamePlatform.objects.get_or_create(
        game=game,
        source_platform_id="route",
        defaults={
            "source_game_platform_id": f"route-{game.pk}",
            "slug": "route",
            "name": "Route",
            "critic_reviews_path": "/critic/",
            "user_reviews_path": "/user/",
        },
    )
    day = datetime(2026, 9, 12, tzinfo=UTC).date() + timedelta(days=game.review_corpora.count())
    cycle, _ = DailyCycle.objects.get_or_create(business_date=day)
    candidate = DailyCandidate.objects.create(
        cycle=cycle, game=game, source_order=1, state="processed"
    )
    ReviewCollectionJob.objects.create(
        daily_candidate=candidate,
        game_platform=route,
        audience=audience,
        state="complete",
        reported_total=10,
        unique_count=10,
        fetched_count=10,
    )
    ReviewCorpusHead.objects.update_or_create(
        game=game,
        audience=audience,
        defaults={
            "corpus": corpus,
            "collection_checkpoint": collection_state(game, audience).checkpoint,
        },
    )
    return corpus


class PendingStateTests(TestCase):
    def test_no_corpus_yet_is_pending(self) -> None:
        game = _make_game(1)
        views = get_summaries(game)
        self.assertEqual({v.audience for v in views}, {"critic", "user"})
        self.assertTrue(all(v.state == "pending" for v in views))


class OkStateTests(TestCase):
    def test_a_succeeded_job_shows_claims_and_provenance(self) -> None:
        game = _make_game(2)
        corpus = _make_corpus(game, "critic", "ok")
        job = SummaryJob.objects.create(
            game=game,
            audience="critic",
            source_corpus=corpus,
            input_fingerprint=corpus.model_input_fingerprint,
            contour_fingerprint=contour_fingerprint(),
            state="succeeded",
        )
        summary = ReviewSummary.objects.create(
            job=job,
            status="ok",
            generated_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
            canonical_output_fingerprint="x",
        )
        support_item = _make_corpus_item(corpus, "ok")
        SummaryClaim.objects.create(
            summary=summary,
            polarity="like",
            ordinal=1,
            claim="Great combat.",
            support_item=support_item,
        )

        views = {v.audience: v for v in get_summaries(game)}
        self.assertEqual(views["critic"].state, "ok")
        self.assertEqual([c.text for c in views["critic"].likes], ["Great combat."])
        self.assertEqual(views["critic"].selected_count, 5)
        self.assertEqual(views["user"].state, "pending")


class InsufficientDataStateTests(TestCase):
    def test_insufficient_data_status_is_surfaced_honestly(self) -> None:
        game = _make_game(3)
        corpus = _make_corpus(game, "user", "insufficient")
        job = SummaryJob.objects.create(
            game=game,
            audience="user",
            source_corpus=corpus,
            input_fingerprint=corpus.model_input_fingerprint,
            contour_fingerprint=contour_fingerprint(),
            state="insufficient_data",
        )
        ReviewSummary.objects.create(
            job=job,
            status="insufficient_data",
            generated_at=datetime(2026, 9, 12, tzinfo=UTC),
            insufficient_reason="not_enough_meaningful_reviews",
            canonical_output_fingerprint="x",
        )

        views = {v.audience: v for v in get_summaries(game)}
        self.assertEqual(views["user"].state, "insufficient_data")
        self.assertEqual(views["user"].likes, [])


class StaleStateTests(TestCase):
    def test_an_old_summary_is_shown_stale_while_a_newer_job_is_in_flight(self) -> None:
        game = _make_game(4)
        old_corpus = _make_corpus(game, "critic", "old")
        old_job = SummaryJob.objects.create(
            game=game,
            audience="critic",
            source_corpus=old_corpus,
            input_fingerprint=old_corpus.model_input_fingerprint,
            contour_fingerprint=contour_fingerprint(),
            state="succeeded",
        )
        ReviewSummary.objects.create(
            job=old_job,
            status="ok",
            generated_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC),
            canonical_output_fingerprint="x",
        )

        new_corpus = _make_corpus(game, "critic", "new")
        SummaryJob.objects.create(
            game=game,
            audience="critic",
            source_corpus=new_corpus,
            input_fingerprint=new_corpus.model_input_fingerprint,
            contour_fingerprint=contour_fingerprint(),
            state="retryable",
        )

        views = {v.audience: v for v in get_summaries(game)}
        self.assertEqual(views["critic"].state, "stale")
        self.assertEqual(views["critic"].stale_reason, "retryable")
