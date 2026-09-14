"""IMP-05 R12/R17/R21: real collection/cache provenance and public card freshness."""

from unittest.mock import patch

from catalog.models import GamePlatform
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from presentation.summaries import SummaryView, get_summaries
from reviews import collector
from reviews.models import ReviewCollectionJob, ReviewCorpus, ReviewCorpusHead
from summaries import worker
from summaries.models import ReviewSummary, SummaryJob

from tests.test_reviews_collector import FakeClock, FakeGateway, _make_job
from tests.test_reviews_snapshots import NOW, next_job, page
from tests.test_summary_admission import ok, process


class SummaryFreshnessTests(TestCase):
    def setUp(self) -> None:
        self.initial = _make_job()
        self.game = self.initial.game_platform.game
        self.clock = FakeClock(NOW)

    def collect(self, day: int, ids: tuple[int, ...] = (1, 2, 3), suffix: str = "") -> ReviewCorpus:
        if day != 12:
            next_job(self.initial, day)
        self.clock.instant = NOW.replace(day=day)
        claim = collector.claim_next_job(self.clock)
        assert claim is not None
        collector.collect_one_page(
            FakeGateway({None: page(*ids, suffix=suffix)}), self.clock, claim
        )
        saved = ReviewCorpus.objects.order_by("-id").first()
        assert saved is not None
        return saved

    def publish(self) -> SummaryJob:
        claim = worker.claim_next_job(self.clock)
        assert claim is not None
        result = process(claim, self.clock, ok)
        self.assertEqual(result.state, "succeeded")
        return result

    def view(self) -> SummaryView:
        return next(value for value in get_summaries(self.game) if value.audience == "critic")

    def test_pending_daily_collection_marks_last_summary_stale(self) -> None:
        self.collect(12)
        self.publish()
        next_job(self.initial, 13)
        self.assertEqual(self.view().state, "stale")
        self.assertEqual(self.view().stale_reason, "collection_in_progress")
        self.assertEqual(self.view().likes[0].text, "Great combat.")

    def test_failed_or_unstable_collection_keeps_last_summary_with_a_reason(self) -> None:
        self.collect(12)
        self.publish()
        newer = next_job(self.initial, 13)
        for state in ("failed", "unstable", "retryable"):
            with self.subTest(state=state):
                ReviewCollectionJob.objects.filter(pk=newer.pk).update(state=state)
                self.assertEqual(self.view().state, "stale")
                self.assertEqual(self.view().stale_reason, f"collection_{state}")

    def test_unsampled_deletion_reuses_summary_and_shows_current_coverage(self) -> None:
        original = self.collect(12, tuple(range(1, 13)))
        original_job = self.publish()
        selected = {
            int(item.review.source_review_id)
            for item in original.items.select_related("review")
            if item.review.source_review_id is not None
        }
        removed = next(i for i in range(1, 13) if i not in selected)
        current = self.collect(13, tuple(i for i in range(1, 13) if i != removed))
        self.assertNotEqual(current.pk, original.pk)
        self.assertEqual(current.model_input_fingerprint, original.model_input_fingerprint)
        self.assertEqual(SummaryJob.objects.count(), 1)
        original_job.refresh_from_db()
        self.assertEqual(original_job.source_corpus_id, original.pk)
        self.assertEqual((self.view().state, self.view().fetched_count), ("ok", 11))

    def test_return_from_a_to_b_to_a_selects_original_cached_summary(self) -> None:
        original = self.collect(12, suffix="A")
        first = self.publish()
        self.collect(13, suffix="B")
        second = self.publish()
        second.summary.claims.update(claim="Summary B.")
        self.collect(14, suffix="A")
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (2, 2))
        self.assertEqual(self.view().state, "ok")
        self.assertEqual(self.view().likes[0].text, "Great combat.")
        self.assertEqual(first.source_corpus_id, original.pk)
        self.assertEqual(self.view().generated_at_utc, NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_equal_corpus_timestamps_do_not_hide_new_input(self) -> None:
        self.collect(12)
        self.publish()
        self.collect(13, suffix="changed")
        ReviewCorpus.objects.update(created_at=NOW)
        self.assertEqual(self.view().state, "stale")
        self.assertEqual(self.view().stale_reason, "pending")

    def test_equal_summary_timestamps_use_id_for_last_valid_fallback(self) -> None:
        self.collect(12)
        self.publish()
        self.collect(13, suffix="B")
        second = self.publish()
        second.summary.claims.update(claim="Summary B.")
        ReviewSummary.objects.update(generated_at=NOW)
        next_job(self.initial, 14)
        self.assertEqual(self.view().state, "stale")
        self.assertEqual(self.view().likes[0].text, "Summary B.")

    def test_contour_change_requires_current_configuration(self) -> None:
        self.collect(12)
        self.publish()
        with patch("summaries.contour.ADAPTER_VERSION", "future"):
            self.assertEqual(self.view().state, "stale")
            self.assertEqual(self.view().stale_reason, "contour_changed")

    def test_generation_restart_and_new_platform_invalidate_freshness(self) -> None:
        self.collect(12)
        self.publish()
        ReviewCollectionJob.objects.filter(pk=self.initial.pk).update(
            collection_generation=1, state="pending"
        )
        self.assertEqual(self.view().state, "stale")
        ReviewCollectionJob.objects.filter(pk=self.initial.pk).update(
            collection_generation=0, state="complete"
        )
        GamePlatform.objects.create(
            game=self.game,
            source_platform_id="p2",
            source_game_platform_id="gp2",
            slug="switch",
            name="Switch",
            critic_reviews_path="/game/g1/critic-reviews/?platform=switch",
        )
        self.assertEqual(self.view().state, "stale")

    def test_content_only_video_is_linked_on_the_card(self) -> None:
        self.game.video_content_url = "https://example.com/trailer.mp4"
        self.game.save(update_fields=["video_content_url"])
        response = self.client.get(f"/games/{self.game.pk}/")
        self.assertContains(response, 'href="https://example.com/trailer.mp4"')
        self.assertContains(response, "Watch trailer")

    def test_legacy_corpus_without_verified_head_is_stale_and_read_path_never_repairs_it(
        self,
    ) -> None:
        self.collect(12)
        self.publish()
        ReviewCorpusHead.objects.all().delete()
        with CaptureQueriesContext(connection) as queries:
            view = self.view()
        self.assertEqual((view.state, view.stale_reason), ("stale", "collection_unverified"))
        self.assertTrue(all(query["sql"].lstrip().startswith("SELECT") for query in queries))
        self.assertFalse(ReviewCorpusHead.objects.exists())

    def test_stale_insufficient_summary_keeps_its_explanation(self) -> None:
        self.collect(12, (1,))
        claim = worker.claim_next_job(self.clock)
        assert claim is not None
        self.assertEqual(process(claim, self.clock, ok).state, "insufficient_data")
        next_job(self.initial, 13)
        response = self.client.get(f"/games/{self.game.pk}/")
        self.assertContains(response, "Stale")
        self.assertContains(response, "New reviews are being collected.")
        self.assertContains(response, "Not enough meaningful reviews yet")

    def test_embed_video_takes_precedence_when_both_sources_exist(self) -> None:
        self.game.video_content_url = "https://example.com/trailer.mp4"
        self.game.video_embed_url = "https://example.com/embed"
        self.game.save(update_fields=["video_content_url", "video_embed_url"])
        response = self.client.get(f"/games/{self.game.pk}/")
        self.assertContains(response, 'href="https://example.com/embed"')
        self.assertNotContains(response, 'href="https://example.com/trailer.mp4"')
