"""IMP-04 / audit R03-R06: desired outcomes through real collection and PostgreSQL."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from catalog.models import GamePlatform, SourceFetch
from django.test import TestCase
from metacritic.dto import ReviewPageDTO
from processing.models import DailyCandidate, DailyCycle
from reviews import collector, corpus
from reviews.models import Review, ReviewCollectionJob, ReviewCorpus, ReviewObservation
from summaries.models import SummaryJob

from tests.test_reviews_collector import FakeClock, FakeGateway, _item, _make_job

NOW = datetime(2026, 9, 12, 10, tzinfo=UTC)


def next_job(previous: ReviewCollectionJob, day: int) -> ReviewCollectionJob:
    cycle, _ = DailyCycle.objects.get_or_create(business_date=NOW.replace(day=day).date())
    candidate, _ = DailyCandidate.objects.get_or_create(
        cycle=cycle,
        game=previous.game_platform.game,
        defaults={"source_order": 1, "state": "processed"},
    )
    return ReviewCollectionJob.objects.create(
        daily_candidate=candidate,
        game_platform=previous.game_platform,
        audience=previous.audience,
    )


def page(*ids: int, suffix: str = "") -> ReviewPageDTO:
    return ReviewPageDTO(
        items=tuple(
            replace(
                _item(i, source_review_id=str(i)), text=f"Review {i}: combat and story {suffix}"
            )
            for i in ids
        ),
        reported_total=len(ids),
        next_cursor=None,
    )


class SnapshotTests(TestCase):
    def setUp(self) -> None:
        self.initial = _make_job()
        self.game = self.initial.game_platform.game
        self.clock = FakeClock(NOW)

    def collect(self, job: ReviewCollectionJob, response: ReviewPageDTO) -> ReviewCollectionJob:
        claim = collector.claim_next_job(self.clock)
        assert claim is not None
        self.assertEqual(claim.pk, job.pk)
        return collector.collect_one_page(
            FakeGateway({job.next_cursor: response}), self.clock, claim
        )

    def test_unchanged_next_day_reuses_versions_corpus_and_summary_job(self) -> None:
        self.collect(self.initial, page(1, 2, 3))
        original = ReviewCorpus.objects.get()
        self.clock.instant += timedelta(days=1)
        updated = self.collect(next_job(self.initial, 13), page(1, 2, 3))
        self.assertEqual(
            (updated.state, updated.unique_count, updated.duplicate_count), ("complete", 3, 0)
        )
        self.assertEqual(Review.objects.count(), 3)
        self.assertEqual(ReviewObservation.objects.count(), 6)
        self.assertEqual(corpus.build(self.game, "critic"), original)
        self.assertEqual(SummaryJob.objects.count(), 1)

    def test_unchanged_next_day_counts_observations_across_multiple_pages(self) -> None:
        for day, job in ((12, self.initial), (13, next_job(self.initial, 13))):
            self.clock.instant = NOW.replace(day=day)
            first = self.collect(job, replace(page(1, 2), reported_total=3, next_cursor="next"))
            second = self.collect(first, replace(page(3), reported_total=3))
            self.assertEqual(
                (second.state, second.unique_count, second.page_count), ("complete", 3, 2)
            )
        self.assertEqual(Review.objects.count(), 3)
        self.assertEqual(ReviewObservation.objects.count(), 6)

    def test_one_edited_text_creates_new_input_without_mutating_old_corpus(self) -> None:
        self.collect(self.initial, page(1, 2, 3, suffix="old"))
        old = ReviewCorpus.objects.get()
        old_items = list(old.items.values_list("review_id", "input_text"))
        changed = replace(
            page(1, 2, 3, suffix="old"),
            items=(
                page(1, suffix="new").items[0],
                *page(2, 3, suffix="old").items,
            ),
        )
        self.collect(next_job(self.initial, 13), changed)
        current = corpus.build(self.game, "critic")
        assert current is not None
        self.assertNotEqual(current.pk, old.pk)
        self.assertNotEqual(current.model_input_fingerprint, old.model_input_fingerprint)
        self.assertEqual(Review.objects.count(), 4)
        self.assertEqual(list(old.items.values_list("review_id", "input_text")), old_items)
        self.assertTrue(current.items.filter(input_text__contains="new").exists())
        self.assertEqual(SummaryJob.objects.count(), 2)

    def test_metadata_only_edits_are_immutable_versions_and_reuse_exact_input(self) -> None:
        original_page = page(1, 2, 3)
        self.collect(self.initial, original_page)
        old = ReviewCorpus.objects.get()
        original_review = self.initial.observations.get(review__identity_key="id:1").review
        previous_fingerprint = old.source_set_fingerprint
        for day, field, value in (
            (13, "score_label", "1"),
            (14, "author_or_source_label", "new author"),
            (15, "date_label", "2026-08-01"),
        ):
            with self.subTest(field=field):
                edited = replace(
                    original_page,
                    items=(
                        replace(original_page.items[0], **{field: value}),
                        *original_page.items[1:],
                    ),
                )
                job = self.collect(next_job(self.initial, day), edited)
                observed = job.observations.get(review__identity_key="id:1").review
                model_field = "author_label" if field == "author_or_source_label" else field
                self.assertEqual(getattr(observed, model_field), value)
                self.assertNotEqual(observed.pk, original_review.pk)
                self.assertEqual(observed.content_sha256, original_review.content_sha256)
                current = corpus.build(self.game, "critic")
                assert current is not None
                self.assertNotEqual(current.source_set_fingerprint, previous_fingerprint)
                self.assertEqual(current.model_input_fingerprint, old.model_input_fingerprint)
                previous_fingerprint = current.source_set_fingerprint
        original_review.refresh_from_db()
        self.assertEqual(original_review.score_label, "8")
        self.assertEqual(SummaryJob.objects.count(), 1)

    def test_deleted_reviews_and_valid_empty_route_do_not_reappear_from_history(self) -> None:
        self.collect(self.initial, page(1, 2, 3))
        original = ReviewCorpus.objects.get()
        self.collect(next_job(self.initial, 13), page(1, 2))
        reduced = corpus.build(self.game, "critic")
        assert reduced is not None
        self.assertEqual(
            (reduced.unique_count, reduced.reported_count, reduced.selected_count), (2, 2, 2)
        )
        self.assertFalse(reduced.items.filter(review__identity_key="id:3").exists())
        self.collect(next_job(self.initial, 14), page())
        empty = corpus.build(self.game, "critic")
        assert empty is not None
        self.assertEqual(
            (empty.unique_count, empty.reported_count, empty.selected_count), (0, 0, 0)
        )
        self.assertEqual(empty.empty_route_count, 1)
        self.assertEqual(original.items.count(), 3)
        self.assertEqual(Review.objects.count(), 3)

    def test_partial_generation_never_contributes_to_a_completed_corpus(self) -> None:
        self.collect(self.initial, page(1, 2, 3))
        old = ReviewCorpus.objects.get()
        new = next_job(self.initial, 13)
        new = self.collect(new, replace(page(4), reported_total=4, next_cursor="next"))
        self.assertIsNone(corpus.build(self.game, "critic"))
        self.assertEqual(ReviewCorpus.objects.count(), 1)
        self.assertEqual(old.items.count(), 3)
        new = self.collect(new, replace(page(1, 2, 3), reported_total=4))
        self.assertEqual(new.state, "complete")
        current = corpus.build(self.game, "critic")
        assert current is not None
        self.assertEqual((current.reported_count, current.unique_count), (4, 4))

    def test_new_incomplete_route_blocks_old_terminal_fallback(self) -> None:
        self.collect(self.initial, page(1, 2, 3))
        latest = next_job(self.initial, 13)
        for state in ("pending", "running", "retryable", "unstable", "failed"):
            with self.subTest(state=state):
                ReviewCollectionJob.objects.filter(pk=latest.pk).update(state=state)
                self.assertIsNone(corpus.build(self.game, "critic"))
        self.assertEqual(ReviewCorpus.objects.count(), 1)

    def test_current_generation_can_reuse_a_previously_superseded_text_version(self) -> None:
        self.collect(self.initial, page(1, 2, 3, suffix="A"))
        original_ids = set(self.initial.observations.values_list("review_id", flat=True))
        self.collect(next_job(self.initial, 13), page(1, 2, 3, suffix="B"))
        reverted = self.collect(next_job(self.initial, 14), page(1, 2, 3, suffix="A"))
        self.assertEqual((reverted.state, reverted.unique_count), ("complete", 3))
        self.assertEqual(
            set(reverted.observations.values_list("review_id", flat=True)), original_ids
        )
        current = corpus.build(self.game, "critic")
        assert current is not None
        self.assertTrue(all(item.input_text.endswith("A") for item in current.items.all()))
        self.assertEqual(Review.objects.count(), 6)

    def test_edit_outside_sample_changes_source_fingerprint_without_new_ai_job(self) -> None:
        self.collect(self.initial, page(*range(11)))
        old = ReviewCorpus.objects.get()
        chosen = set(old.items.values_list("review__identity_key", flat=True))
        omitted = next(i for i in range(11) if f"id:{i}" not in chosen)
        original_page = page(*range(11))
        edited = replace(
            original_page,
            items=tuple(
                replace(item, text="Edited outside the exact input")
                if item.source_review_id == str(omitted)
                else item
                for item in original_page.items
            ),
        )
        self.collect(next_job(self.initial, 13), edited)
        current = corpus.build(self.game, "critic")
        assert current is not None
        self.assertNotEqual(current.source_set_fingerprint, old.source_set_fingerprint)
        self.assertEqual(current.model_input_fingerprint, old.model_input_fingerprint)
        self.assertEqual(SummaryJob.objects.count(), 1)

    def test_missing_current_platform_job_does_not_mix_daily_candidates(self) -> None:
        second_platform = GamePlatform.objects.create(
            game=self.game,
            source_platform_id="p2",
            source_game_platform_id="gp2",
            slug="ps5",
            name="PlayStation 5",
            critic_reviews_path="/game/g1/critic-reviews/?platform=ps5",
        )
        second = ReviewCollectionJob.objects.create(
            daily_candidate=self.initial.daily_candidate,
            game_platform=second_platform,
            audience="critic",
        )
        self.collect(self.initial, page(1, 2, 3))
        self.collect(second, page(4, 5, 6))
        self.assertEqual(ReviewCorpus.objects.count(), 1)
        self.collect(next_job(self.initial, 13), page(1, 2, 3, suffix="new"))
        self.assertIsNone(corpus.build(self.game, "critic"))
        self.assertEqual(ReviewCorpus.objects.count(), 1)
        self.collect(next_job(second, 13), page(4, 5, 6, suffix="new"))
        current = corpus.build(self.game, "critic")
        assert current is not None
        self.assertEqual(current.unique_count, 6)
        self.assertTrue(all(item.input_text.endswith("new") for item in current.items.all()))

    def test_late_older_daily_job_cannot_replace_a_newer_snapshot(self) -> None:
        self.collect(self.initial, page(1, 2, 3, suffix="old"))
        self.collect(next_job(self.initial, 14), page(1, 2, 3, suffix="current"))
        current = corpus.build(self.game, "critic")
        self.clock.instant += timedelta(days=4)
        self.collect(next_job(self.initial, 13), page(1, 2, 3, suffix="late old day"))
        self.assertEqual(corpus.build(self.game, "critic"), current)

    def test_handoff_failure_rolls_back_terminal_page_and_reclaim_completes_it(self) -> None:
        first = self.collect(self.initial, replace(page(1), reported_total=3, next_cursor="next"))
        with patch(
            "summaries.worker.ensure_job", side_effect=RuntimeError("crash after corpus insert")
        ):
            with self.assertRaises(RuntimeError):
                self.collect(first, replace(page(2, 3), reported_total=3))
        first.refresh_from_db()
        self.assertEqual((first.state, first.next_cursor, first.page_count), ("running", "next", 1))
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(ReviewObservation.objects.count(), 1)
        self.assertEqual(SourceFetch.objects.filter(kind="review_page").count(), 2)
        self.assertEqual(SourceFetch.objects.filter(outcome="started").count(), 1)
        self.assertEqual(ReviewCorpus.objects.count(), 0)
        self.assertEqual(SummaryJob.objects.count(), 0)
        self.clock.instant += collector.LEASE_TTL + timedelta(seconds=1)
        restored = self.collect(first, replace(page(2, 3), reported_total=3))
        self.assertEqual(restored.state, "complete")
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (1, 1))
        self.assertEqual(self.initial.daily_candidate.state, "processed")
        self.assertEqual(SourceFetch.objects.filter(outcome="abandoned").count(), 1)

    def test_crash_after_terminal_commit_already_has_durable_summary_job(self) -> None:
        self.collect(self.initial, page(1, 2, 3))
        self.initial.refresh_from_db()
        self.assertEqual(self.initial.state, "complete")
        self.clock.instant += timedelta(days=1)
        self.assertIsNone(collector.claim_next_job(self.clock))
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (1, 1))

    def test_duplicate_identity_is_not_a_second_review_even_if_unique_total_matches(self) -> None:
        result = self.collect(self.initial, replace(page(1, 1, 2), reported_total=2))
        self.assertEqual(
            (result.state, result.fetched_count, result.unique_count, result.duplicate_count),
            ("unstable", 3, 2, 1),
        )
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (0, 0))

    def test_identity_edited_mid_route_cannot_mix_versions_into_a_snapshot(self) -> None:
        first = self.collect(self.initial, replace(page(1), reported_total=3, next_cursor="next"))
        result = self.collect(first, page(1, 2, 3, suffix="changed during pagination"))
        self.assertEqual(
            (result.state, result.last_error), ("unstable", "review_changed_during_collection")
        )
        self.assertEqual((Review.objects.count(), ReviewObservation.objects.count()), (1, 1))
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (0, 0))

    def test_terminal_counts_require_observations_from_matching_successful_generation(self) -> None:
        self.collect(self.initial, page(1, 2, 3))
        for target, changes, restore in (
            (
                self.initial.observations.all(),
                {"collection_generation": 2},
                {"collection_generation": 1},
            ),
            (
                SourceFetch.objects.filter(review_job=self.initial),
                {"collection_generation": 2},
                {"collection_generation": 1},
            ),
            (
                SourceFetch.objects.filter(review_job=self.initial),
                {"outcome": "failed"},
                {"outcome": "succeeded"},
            ),
        ):
            with self.subTest(changes=changes):
                target.update(**changes)
                self.assertIsNone(corpus.build(self.game, "critic"))
                target.update(**restore)
        observation = self.initial.observations.first()
        assert observation is not None
        observation.delete()
        self.assertIsNone(corpus.build(self.game, "critic"))

    def test_new_empty_platform_changes_coverage_fingerprint_without_new_model_input(self) -> None:
        self.collect(self.initial, page(1, 2, 3))
        old = ReviewCorpus.objects.get()
        platform = GamePlatform.objects.create(
            game=self.game,
            source_platform_id="p2",
            source_game_platform_id="gp2",
            slug="ps5",
            name="PlayStation 5",
            critic_reviews_path="/game/g1/critic-reviews/?platform=ps5",
        )
        self.assertIsNone(corpus.build(self.game, "critic"))
        job = ReviewCollectionJob.objects.create(
            daily_candidate=self.initial.daily_candidate, game_platform=platform, audience="critic"
        )
        self.collect(job, page())
        current = corpus.build(self.game, "critic")
        assert current is not None
        self.assertEqual((current.complete_route_count, current.empty_route_count), (1, 1))
        self.assertNotEqual(current.source_set_fingerprint, old.source_set_fingerprint)
        self.assertEqual(current.model_input_fingerprint, old.model_input_fingerprint)
        self.assertEqual(SummaryJob.objects.count(), 1)

    def test_same_source_ids_in_two_audiences_stay_separate(self) -> None:
        self.collect(self.initial, page(1, 2, 3, suffix="critics"))
        job = ReviewCollectionJob.objects.create(
            daily_candidate=self.initial.daily_candidate,
            game_platform=self.initial.game_platform,
            audience="user",
        )
        self.collect(job, page(1, 2, 3, suffix="users"))
        current = corpus.build(self.game, "user")
        assert current is not None
        self.assertTrue(all(item.input_text.endswith("users") for item in current.items.all()))
        self.assertEqual(set(current.items.values_list("review__audience", flat=True)), {"user"})
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (2, 2))

    def test_identical_cross_platform_reviews_deduplicate_with_correct_item_provenance(
        self,
    ) -> None:
        second_platform = GamePlatform.objects.create(
            game=self.game,
            source_platform_id="p2",
            source_game_platform_id="gp2",
            slug="ps5",
            name="PlayStation 5",
            critic_reviews_path="/game/g1/critic-reviews/?platform=ps5",
        )
        second = ReviewCollectionJob.objects.create(
            daily_candidate=self.initial.daily_candidate,
            game_platform=second_platform,
            audience="critic",
        )
        self.collect(self.initial, page(1, 2, 3))
        self.collect(second, page(1, 2, 3))
        current = ReviewCorpus.objects.get()
        self.assertEqual(
            (current.unique_count, current.deduplicated_count, current.selected_count), (6, 3, 3)
        )
        self.assertEqual(
            set(current.items.values_list("review__game_platform_id", flat=True)),
            {self.initial.game_platform_id},
        )
        self.assertTrue(
            all(item.input_text == item.review.text_original for item in current.items.all())
        )
