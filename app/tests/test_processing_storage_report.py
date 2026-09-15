import hashlib
from datetime import UTC, datetime

from catalog.models import Game, GamePlatform, SourceFetch
from django.test import TestCase
from processing.models import DailyCandidate, DailyCycle
from processing.storage_report import storage_report
from reviews.models import Review, ReviewCollectionJob, ReviewCorpus, ReviewObservation
from reviews.versioning import version_fingerprint
from summaries.models import SummaryAttempt, SummaryJob


def _make_fetch(n: int) -> SourceFetch:
    return SourceFetch.objects.create(
        kind="review_page",
        url=f"https://backend.metacritic.com/reviews/{n}",
        started_at=datetime(2026, 9, 12, tzinfo=UTC),
        completed_at=datetime(2026, 9, 12, tzinfo=UTC),
        parser_contract_version="1.0.0",
        outcome="succeeded",
    )


class StorageReportOverheadTests(TestCase):
    """HRD-05: the report must not silently collapse to O(unique reviews) -- these seed a
    deliberately non-trivial multiplier (more than one text version per identity, more than one
    observation per review, more than one attempt per terminal job) and assert the report reveals
    each ratio, rather than reporting only the smaller, unique-side count."""

    def test_repeated_observations_and_text_versions_are_both_visible(self) -> None:
        game = Game.objects.create(
            source_game_id="g1", canonical_locator="/game/g1/", title="Game 1"
        )
        platform = GamePlatform.objects.create(
            game=game, source_platform_id="p1", source_game_platform_id="gp1", slug="pc", name="PC"
        )
        cycle = DailyCycle.objects.create(business_date="2026-09-12")
        candidate = DailyCandidate.objects.create(cycle=cycle, game=game, source_order=1)
        job = ReviewCollectionJob.objects.create(
            daily_candidate=candidate, game_platform=platform, audience="critic"
        )

        # Same identity, two text versions (an edited review re-observed with new content).
        original = Review.objects.create(
            game_platform=platform,
            audience="critic",
            identity_key="id:1",
            text_original="Original text.",
            content_sha256="sha-a",
            version_sha256=version_fingerprint("Original text.", None, None, None),
            first_seen_at=datetime(2026, 9, 12, tzinfo=UTC),
        )
        edited = Review.objects.create(
            game_platform=platform,
            audience="critic",
            identity_key="id:1",
            text_original="Edited text.",
            content_sha256="sha-b",
            version_sha256=version_fingerprint("Edited text.", None, None, None),
            first_seen_at=datetime(2026, 9, 12, tzinfo=UTC),
            supersedes=original,
        )
        # Three observations of the same review row, across three distinct fetches/generations.
        for generation in range(3):
            fetch = _make_fetch(generation)
            ReviewObservation.objects.create(
                collection_job=job,
                collection_generation=generation,
                source_fetch=fetch,
                review=original,
                page_position=0,
                route_global_position=0,
            )

        report = storage_report()

        self.assertEqual(report["text_versions"]["review_rows"], 2)
        self.assertEqual(report["text_versions"]["distinct_identities"], 1)
        self.assertEqual(report["text_versions"]["versions_per_identity"], 2.0)
        self.assertEqual(report["repeated_observations"]["review_rows"], 2)
        self.assertEqual(report["repeated_observations"]["observation_rows"], 3)
        self.assertGreater(report["repeated_observations"]["observations_per_review"], 1)
        self.assertIsNotNone(edited.supersedes_id)

    def test_multiple_attempts_per_terminal_job_are_visible(self) -> None:
        game = Game.objects.create(
            source_game_id="g2", canonical_locator="/game/g2/", title="Game 2"
        )
        corpus_fingerprint_seed = f"fp-{game.id}"
        corpus = ReviewCorpus.objects.create(
            game=game,
            audience="critic",
            policy_version="1.0.0-candidate",
            source_set_fingerprint=hashlib.sha256(corpus_fingerprint_seed.encode()).hexdigest(),
            model_input_fingerprint=hashlib.sha256(f"in-{game.id}".encode()).hexdigest(),
            complete_route_count=1,
            empty_route_count=0,
            reported_count=3,
            fetched_count=3,
            unique_count=3,
            deduplicated_count=0,
            selected_count=3,
            tokenizer_id="o200k_harmony",
            tokenizer_version="0.14.0",
            raw_prompt_tokens=100,
            guarded_prompt_tokens=164,
            completion_reservation=800,
        )
        job = SummaryJob.objects.create(
            game=game,
            audience="critic",
            source_corpus=corpus,
            input_fingerprint=corpus.model_input_fingerprint,
            contour_fingerprint=hashlib.sha256(b"contour").hexdigest(),
            state="succeeded",
            attempt_count=2,
        )
        for attempt_no in (1, 2):
            SummaryAttempt.objects.create(
                job=job,
                attempt_no=attempt_no,
                provider="groq",
                api_kind="chat_completions",
                requested_model="openai/gpt-oss-20b",
                contour_versions={},
                generation_params={},
                estimated_prompt_tokens=100,
                reserved_total_tokens=200,
                started_at=datetime(2026, 9, 12, tzinfo=UTC),
            )

        report = storage_report()

        self.assertEqual(report["attempts"]["attempt_rows"], 2)
        self.assertEqual(report["attempts"]["terminal_job_rows"], 1)
        self.assertEqual(report["attempts"]["attempts_per_terminal_job"], 2.0)

    def test_empty_database_reports_null_ratios_not_a_crash(self) -> None:
        report = storage_report()

        self.assertIsNone(report["text_versions"]["versions_per_identity"])
        self.assertIsNone(report["repeated_observations"]["observations_per_review"])
        self.assertIsNone(report["attempts"]["attempts_per_terminal_job"])
        self.assertIsInstance(report["database_size_bytes"], int)
        self.assertGreater(report["database_size_bytes"], 0)

    def test_a_permission_denied_measurement_does_not_poison_a_surrounding_transaction(
        self,
    ) -> None:
        """`pg_ls_waldir()` needs superuser/`pg_monitor`, which the test DB role deliberately
        lacks (same least-privilege posture as the real web role) -- so this exercises the real
        permission-denied path, not a simulated one. Without each risky query running in its own
        savepoint, that failure would abort the whole ambient transaction (every `TestCase` test
        runs inside one), and this test's own final query would fail with a misleading "current
        transaction is aborted" instead of ever seeing the report complete."""
        report = storage_report()

        self.assertIsNone(report["wal_size_bytes"])
        # If the WAL query's failure had poisoned this test's ambient transaction, this would
        # raise `django.db.utils.InternalError: current transaction is aborted` instead of 0.
        self.assertEqual(Review.objects.count(), 0)
