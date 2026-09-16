"""OPS-01: independent liveness, stale detection and fencing of observation instances."""

import time
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from unittest.mock import patch

from django.db import DatabaseError, connections
from django.test import TransactionTestCase, override_settings
from processing.heartbeat import Heartbeat, report_progress
from processing.models import ProcessHeartbeat, ProcessingLease
from processing.monitoring import snapshot

from tests.test_processing_scheduler import FakeClock

NOW = datetime(2026, 9, 16, 10, tzinfo=UTC)


class ProcessHeartbeatTests(TransactionTestCase):
    def test_failed_registration_can_be_retried_after_database_recovers(self) -> None:
        observer = Heartbeat("worker", clock=FakeClock(NOW))
        with patch("processing.heartbeat.ProcessHeartbeat.objects.filter") as rows:
            rows.return_value.update.side_effect = DatabaseError("temporary write failure")
            with self.assertRaises(DatabaseError):
                observer.register()
        self.assertEqual(ProcessHeartbeat.objects.count(), 0)
        self.assertEqual(observer.generation, 0)
        observer.register()
        self.assertTrue(observer.publish())
        self.assertEqual(snapshot(FakeClock(NOW))["processes"][1]["status"], "idle")

    def test_stale_overdue_and_new_instance_do_not_change_work_lease(self) -> None:
        clock = FakeClock(NOW)
        old = Heartbeat("worker", clock=clock)
        old.register()
        old.activity("summary", job_id=42, deadline_seconds=2)
        old.publish()
        clock.instant += timedelta(seconds=3)
        data = snapshot(clock)["processes"][1]
        self.assertEqual(data["status"], "busy")
        self.assertTrue(data["overdue"])
        clock.instant += timedelta(seconds=1)
        self.assertEqual(snapshot(clock)["processes"][1]["status"], "stale")
        self.assertEqual(ProcessingLease.objects.count(), 0)
        new = Heartbeat("worker", clock=clock)
        new.register()
        self.assertFalse(old.publish(stopped=True))
        self.assertEqual(snapshot(clock)["processes"][1]["status"], "idle")
        self.assertTrue(new.publish(stopped=True))
        self.assertEqual(snapshot(clock)["processes"][1]["status"], "stopped")

    def test_heartbeat_continues_while_main_work_is_blocked(self) -> None:
        blocked, release = Event(), Event()
        errors: list[BaseException] = []

        def work() -> None:
            try:
                with Heartbeat("scheduler", interval=0.1):
                    report_progress("source_request", run_id=7, deadline_seconds=1)
                    blocked.set()
                    release.wait(8)
            except BaseException as error:
                errors.append(error)
            finally:
                connections.close_all()

        thread = Thread(target=work)
        thread.start()
        try:
            self.assertTrue(blocked.wait(5))
            deadline = time.monotonic() + 5
            first = None
            while time.monotonic() < deadline:
                row = ProcessHeartbeat.objects.first()
                if row and first is None:
                    first = row.last_seen_at
                if row and first and (row.last_seen_at - first).total_seconds() > 1.2:
                    break
                time.sleep(0.05)
            else:
                self.fail("Heartbeat did not advance during blocked work")
            data = snapshot()["processes"][0]
            self.assertEqual(data["status"], "busy")
            self.assertEqual(data["run_id"], 7)
            self.assertTrue(data["overdue"])
        finally:
            release.set()
            thread.join(8)
        self.assertEqual(errors, [])
        self.assertFalse(thread.is_alive())
        self.assertEqual(snapshot()["processes"][0]["status"], "stopped")

    @override_settings(OPS_MONITORING_ENABLED=False)
    def test_disabled_telemetry_does_not_create_a_thread_or_rows(self) -> None:
        with Heartbeat("worker"):
            report_progress("summary", job_id=1)
        self.assertEqual(ProcessHeartbeat.objects.count(), 0)
