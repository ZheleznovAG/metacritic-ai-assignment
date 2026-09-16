"""BON-21 / AC-OPS-01/02: committed progress, recovery and read-only public state."""

import json
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from unittest.mock import patch

from django.db import DatabaseError, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from metacritic.dto import FetchEvidence, GameDTO
from processing.models import (
    CoreAttempt,
    DailyCandidate,
    ProcessingLease,
    ProcessingRun,
    RunCandidate,
)
from processing.monitoring import HISTORY_LIMIT, snapshot
from processing.progress import progress_for_runs
from processing.scheduler import run_tick

from tests.test_processing_scheduler import FakeClock
from tests.test_processing_selector import FakeGateway, _identity

NOW = datetime(2026, 9, 16, 10, tzinfo=UTC)


class MonitoringTests(TransactionTestCase):
    def test_live_counters_follow_commits_before_terminal_run_record(self) -> None:
        blocked, release = Event(), Event()
        errors: list[BaseException] = []

        class PausingGateway(FakeGateway):
            def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
                if url.endswith("/g2/"):
                    blocked.set()
                    if not release.wait(10):
                        raise RuntimeError("Test did not release HTTP")
                return super().fetch_game(url)

        def work() -> None:
            try:
                run_tick(PausingGateway([_identity(n) for n in range(1, 4)]), FakeClock(NOW))
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        thread = Thread(target=work)
        thread.start()
        try:
            self.assertTrue(blocked.wait(10))
            data = snapshot(FakeClock(NOW))
            active = data["active_run"]
            self.assertEqual(
                (active["selected"], active["processed"], active["failed"], active["attempts"]),
                (3, 1, 0, 2),
            )
            self.assertEqual(data["today"]["found"], 3)
            self.assertEqual(ProcessingRun.objects.get().processed_count, 0)
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        final = snapshot(FakeClock(NOW))["history"][0]
        self.assertEqual(
            (final["processed"], final["failed"], final["status"]), (3, 0, "succeeded")
        )
        self.assertIsNone(snapshot(FakeClock(NOW))["active_run"])

    def test_snapshot_queries_share_one_repeatable_read_version(self) -> None:
        run_tick(FakeGateway([_identity(1)]), FakeClock(NOW))
        original = progress_for_runs
        errors: list[BaseException] = []

        def update_after_runs_read() -> None:
            try:
                run_tick(FakeGateway([_identity(2)]), FakeClock(NOW + timedelta(days=1)))
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        def interleaved(run_ids: list[int]) -> object:
            thread = Thread(target=update_after_runs_read)
            thread.start()
            thread.join(10)
            self.assertFalse(thread.is_alive())
            return original(run_ids)

        with patch("processing.monitoring.progress_for_runs", side_effect=interleaved):
            data = snapshot(FakeClock(NOW + timedelta(days=1)))
        self.assertEqual(errors, [])
        self.assertEqual(len(data["history"]), 1)
        self.assertEqual(data["today"]["found"], 0)
        self.assertEqual(snapshot(FakeClock(NOW + timedelta(days=1)))["today"]["found"], 1)

    def test_history_is_bounded_and_query_count_does_not_grow_per_run(self) -> None:
        run_tick(FakeGateway([_identity(1)]), FakeClock(NOW))
        with CaptureQueriesContext(connection) as small:
            snapshot(FakeClock(NOW))
        ProcessingRun.objects.bulk_create(
            [
                ProcessingRun(trigger_key=f"history:{n}", scheduled_slot=NOW, status="succeeded")
                for n in range(30)
            ]
        )
        with CaptureQueriesContext(connection) as large:
            data = snapshot(FakeClock(NOW))
        self.assertEqual(len(data["history"]), HISTORY_LIMIT)
        self.assertEqual(len(large), len(small))
        self.assertLess(len(json.dumps(data).encode()), 64 * 1024)

    def test_snapshot_is_read_only_and_public_errors_are_allowlisted(self) -> None:
        run = ProcessingRun.objects.create(
            trigger_key="never-expose-secret",
            scheduled_slot=NOW,
            status="failed",
            error_code="private-token",
        )
        with patch(
            "processing.monitoring._snapshot",
            side_effect=lambda clock: ProcessingRun.objects.filter(pk=run.pk).update(
                status="running"
            ),
        ):
            with self.assertRaises(DatabaseError):
                snapshot(FakeClock(NOW))
        response = self.client.get("/ops/status/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotContains(response, "private-token")
        self.assertNotContains(response, "never-expose-secret")
        self.assertEqual(response.json()["history"][0]["error"], "processing_error")
        self.assertEqual(self.client.post("/ops/status/").status_code, 405)
        with patch("presentation.monitoring.snapshot", side_effect=DatabaseError("sensitive DSN")):
            response = self.client.get("/ops/status/")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"status": "unavailable"})
            response = self.client.get("/ops/")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(b"sensitive DSN", response.content)

    @override_settings(OPS_MONITORING_ENABLED=False)
    def test_flag_disables_endpoints_and_navigation_without_disabling_catalog(self) -> None:
        self.assertEqual(self.client.get("/ops/").status_code, 404)
        self.assertEqual(self.client.get("/ops/status/").status_code, 404)
        self.assertNotContains(self.client.get("/"), 'href="/ops/"')

    def test_unknown_processes_and_empty_history_have_honest_states(self) -> None:
        data = snapshot(FakeClock(NOW))
        self.assertEqual([row["status"] for row in data["processes"]], ["unknown", "unknown"])
        self.assertEqual(data["history"], [])
        self.assertEqual(data["reviews"]["outstanding"], 0)
        self.assertIsNone(data["summaries"]["oldest_wait_seconds"])
        self.assertContains(self.client.get("/ops/"), "No runs recorded yet")


class BatchRecoveryTests(TransactionTestCase):
    def test_upgrade_preserves_history_and_never_invents_legacy_batch_members(self) -> None:
        clock = FakeClock(NOW)
        original = run_tick(FakeGateway([_identity(1), _identity(2)]), clock).run
        attempts = list(CoreAttempt.objects.values_list("id", "candidate_id", "outcome"))
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(
                [("processing", "0002_processingrun_remove_dailycycle_exhausted_and_more")]
            )
            # Existing terminal rows and a pre-upgrade abandoned run both survive additive DDL.
            ProcessingRun.objects.filter(pk=original.pk).update(status="running")
            MigrationExecutor(connection).migrate(latest)
        finally:
            MigrationExecutor(connection).migrate(latest)
        gateway = FakeGateway([_identity(3)])
        with patch.object(gateway, "fetch_game") as fetch:
            result = run_tick(gateway, clock)
        fetch.assert_not_called()
        self.assertEqual(result.run.error_code, "legacy_batch_unavailable")
        self.assertEqual((result.run.processed_count, result.run.selected_count), (2, 2))
        self.assertEqual(
            list(CoreAttempt.objects.values_list("id", "candidate_id", "outcome")), attempts
        )
        self.assertEqual(RunCandidate.objects.count(), 0)

    def test_stale_instance_does_not_release_a_still_running_new_generation(self) -> None:
        clock = FakeClock(NOW)
        gateway = FakeGateway([_identity(1)])
        fetch = gateway.fetch_game

        def replaced(url: str) -> tuple[GameDTO | None, FetchEvidence]:
            run = ProcessingRun.objects.get()
            token = (run.fencing_token or 0) + 1
            ProcessingRun.objects.filter(pk=run.pk).update(fencing_token=token)
            ProcessingLease.objects.update(fencing_token=token)
            return fetch(url)

        with patch.object(gateway, "fetch_game", side_effect=replaced):
            result = run_tick(gateway, clock)
        self.assertEqual(result.run.status, "running")
        self.assertIsNone(result.run.error_code)
        self.assertEqual(ProcessingLease.objects.get().owner_run_id, result.run.pk)

    def test_crash_resumes_the_same_twenty_without_recounting_attempts(self) -> None:
        clock = FakeClock(NOW)
        gateway = FakeGateway([_identity(n) for n in range(1, 21)], failing_games={"g1"})
        fetch = gateway.fetch_game
        calls: list[str] = []

        def crash(url: str) -> tuple[GameDTO | None, FetchEvidence]:
            calls.append(url)
            if url.endswith("/g3/"):
                raise SystemExit("simulated process death")
            return fetch(url)

        with patch.object(gateway, "fetch_game", side_effect=crash):
            with self.assertRaises(SystemExit):
                run_tick(gateway, clock)
        run = ProcessingRun.objects.get()
        self.assertEqual(RunCandidate.objects.filter(run=run).count(), 20)
        self.assertEqual(CoreAttempt.objects.filter(run=run).count(), 3)
        original_members = set(run.batch.values_list("candidate_id", flat=True))
        gateway.new_releases = [_identity(n) for n in range(21, 41)]
        resumed = run_tick(gateway, clock)
        self.assertEqual(resumed.run.pk, run.pk)
        self.assertEqual(
            (resumed.run.selected_count, resumed.run.processed_count, resumed.run.failed_count),
            (20, 19, 1),
        )
        self.assertEqual(set(run.batch.values_list("candidate_id", flat=True)), original_members)
        self.assertEqual(DailyCandidate.objects.count(), 20)
        self.assertEqual(CoreAttempt.objects.filter(run=run).count(), 21)
        final = snapshot(clock)["history"][0]
        self.assertEqual(
            (final["selected"], final["processed"], final["failed"], final["attempts"]),
            (20, 19, 1, 21),
        )

    def test_late_same_run_owner_cannot_close_or_release_resumed_generation(self) -> None:
        clock = FakeClock(NOW)
        gateway = FakeGateway([_identity(1), _identity(2)])
        fetch = gateway.fetch_game
        resumed = False

        def after_reclaim(url: str) -> tuple[GameDTO | None, FetchEvidence]:
            nonlocal resumed
            if not resumed:
                resumed = True
                clock.instant += timedelta(minutes=46)
                current = run_tick(FakeGateway([]), clock)
                self.assertEqual(current.run.processed_count, 2)
            return fetch(url)

        with patch.object(gateway, "fetch_game", side_effect=after_reclaim):
            result = run_tick(gateway, clock)
        self.assertEqual(result.run.status, "succeeded")
        self.assertIsNone(result.run.error_code)
        self.assertEqual((result.run.selected_count, result.run.processed_count), (2, 2))
        self.assertEqual(ProcessingRun.objects.count(), 1)
        self.assertIsNone(ProcessingLease.objects.get().owner_run_id)
