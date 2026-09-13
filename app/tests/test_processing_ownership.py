"""IMP-03 / R16,R20: ownership before mutation and durable bounded core attempts."""

from datetime import timedelta
from unittest.mock import patch

from catalog.models import Game
from django.test import TestCase
from metacritic.dto import BrowsePage, FetchEvidence, GameDTO
from processing.lease import StaleRun
from processing.models import CoreAttempt, DailyCandidate, DailyCycle
from processing.runner import process_candidate
from processing.scheduler import run_tick
from processing.selector import run_batch

from tests.test_processing_selector import FakeGateway, _acquire, _identity, _make_run
from tests.test_reviews_collector import FakeClock
from tests.test_reviews_snapshots import NOW


class CoreOwnershipTests(TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(NOW)
        self.processing_run = _make_run(self.clock, NOW, 0)
        _acquire(self.processing_run, self.clock)
        cycle = DailyCycle.objects.create(business_date=NOW.date(), phase="browse")
        game = Game.objects.create(source_game_id="g1", canonical_locator="/game/g1/", title="G1")
        self.candidate = DailyCandidate.objects.create(cycle=cycle, game=game, source_order=1)

    def test_stale_owner_does_not_fetch_or_reopen_processed_candidate(self) -> None:
        self.clock.instant += timedelta(hours=1)
        run_tick(FakeGateway(), self.clock)
        with patch.object(FakeGateway, "fetch_game") as fetch:
            with self.assertRaises(StaleRun):
                process_candidate(FakeGateway(), self.clock, self.processing_run, self.candidate)
            fetch.assert_not_called()
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.state, "processed")
        self.clock.instant += timedelta(hours=1)
        self.assertEqual(run_tick(FakeGateway(), self.clock).run.processed_count, 0)
        self.assertEqual(CoreAttempt.objects.filter(outcome="succeeded").count(), 1)

    def test_stale_batch_cannot_recover_new_owners_processing_candidate(self) -> None:
        self.clock.instant += timedelta(hours=1)
        newer = _make_run(self.clock, self.clock.instant, 1)
        _acquire(newer, self.clock)
        DailyCandidate.objects.filter(pk=self.candidate.pk).update(state="processing")
        with self.assertRaises(StaleRun):
            run_batch(FakeGateway(), self.clock, self.processing_run)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.state, "processing")

    def test_expired_lease_without_reclaim_cannot_start_http(self) -> None:
        self.clock.instant += timedelta(hours=1)
        with patch.object(FakeGateway, "fetch_game") as fetch:
            with self.assertRaises(StaleRun):
                process_candidate(FakeGateway(), self.clock, self.processing_run, self.candidate)
            fetch.assert_not_called()
        self.candidate.refresh_from_db()
        self.assertEqual((self.candidate.state, self.candidate.attempt_count), ("pending", 0))

    def test_same_claim_cannot_reprocess_completed_candidate(self) -> None:
        process_candidate(FakeGateway(), self.clock, self.processing_run, self.candidate)
        with patch.object(FakeGateway, "fetch_game") as fetch:
            process_candidate(FakeGateway(), self.clock, self.processing_run, self.candidate)
            fetch.assert_not_called()
        self.assertEqual(CoreAttempt.objects.count(), 1)

    def test_stale_response_cannot_overwrite_new_owner_result(self) -> None:
        gateway = FakeGateway()
        fetch = gateway.fetch_game

        def response_after_reclaim(url: str) -> tuple[GameDTO | None, FetchEvidence]:
            self.clock.instant += timedelta(hours=1)
            run_tick(FakeGateway(), self.clock)
            return fetch(url)

        with patch.object(gateway, "fetch_game", side_effect=response_after_reclaim):
            with self.assertRaises(StaleRun):
                process_candidate(gateway, self.clock, self.processing_run, self.candidate)
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.state, "processed")
        self.assertEqual(CoreAttempt.objects.filter(outcome="succeeded").count(), 1)


class CoreRetryLimitTests(TestCase):
    def test_fifth_failure_frees_capacity_and_reopen_cannot_reset_budget(self) -> None:
        clock = FakeClock(NOW)
        gateway = FakeGateway(
            new_releases=[_identity(i) for i in range(1, 21)],
            failing_games={f"g{i}" for i in range(1, 21)},
        )
        for _ in range(5):
            run_tick(gateway, clock)
            clock.instant += timedelta(hours=1)
        self.assertEqual(DailyCandidate.objects.filter(state="failed", attempt_count=5).count(), 20)
        # Simulate an operator reopening the state without deleting attempt history.
        DailyCandidate.objects.update(state="retryable", attempt_count=0)
        gateway.new_releases = []
        gateway.browse_pages = {1: BrowsePage(games=(_identity(21),), has_next_page=False)}
        result = run_tick(gateway, clock)
        self.assertEqual((result.run.selected_count, result.run.processed_count), (1, 1))
        self.assertEqual(CoreAttempt.objects.count(), 101)
        self.assertEqual(DailyCandidate.objects.filter(state="failed").count(), 20)

    def test_crash_and_restart_consume_the_same_durable_attempt_budget(self) -> None:
        clock = FakeClock(NOW)
        gateway = FakeGateway(new_releases=[_identity(1)])
        for _ in range(5):
            with patch.object(gateway, "fetch_game", side_effect=RuntimeError("process crashed")):
                with self.assertRaises(RuntimeError):
                    run_tick(gateway, clock)
            clock.instant += timedelta(hours=1)
        result = run_tick(gateway, clock)
        candidate = DailyCandidate.objects.get()
        self.assertEqual((candidate.state, candidate.attempt_count), ("failed", 5))
        self.assertEqual(result.run.selected_count, 0)
        self.assertEqual(CoreAttempt.objects.filter(outcome="failed").count(), 5)
