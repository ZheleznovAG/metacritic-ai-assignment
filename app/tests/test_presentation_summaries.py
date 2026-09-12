from datetime import UTC, datetime

from catalog.models import Game, GamePlatform
from django.test import TestCase
from presentation.summaries import get_summaries
from reviews.models import Review, ReviewCorpus, ReviewCorpusItem
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
    return ReviewCorpus.objects.create(
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
            input_fingerprint="fp1",
            contour_fingerprint="cf1",
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
            input_fingerprint="fp2",
            contour_fingerprint="cf1",
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
            input_fingerprint="fp-old",
            contour_fingerprint="cf1",
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
            input_fingerprint="fp-new",
            contour_fingerprint="cf1",
            state="retryable",
        )

        views = {v.audience: v for v in get_summaries(game)}
        self.assertEqual(views["critic"].state, "stale")
        self.assertEqual(views["critic"].stale_reason, "retryable")
