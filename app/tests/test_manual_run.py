"""BON-22: `processing.scheduler.run_manual` reuses the exact same lease/resume/execute/close
machinery as the hourly `run_tick` (`tests/test_processing_scheduler.py`'s fakes), keyed by a
`ManualRunRequest` instead of an hourly slot."""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase
from processing.lease import acquire_lease
from processing.models import ManualRunRequest, ProcessingRun
from processing.scheduler import run_manual

from tests.test_processing_scheduler import FakeClock, FakeGateway, _identity


def _operator() -> User:
    return get_user_model().objects.create_user(username="op", password="x" * 12)


def _queued_request(created_at: datetime | None = None) -> ManualRunRequest:
    return ManualRunRequest.objects.create(
        request_id=uuid.uuid4(),
        operator=_operator(),
        created_at=created_at or datetime(2026, 9, 16, 14, 0, tzinfo=UTC),
    )


class RunManualTests(TestCase):
    def test_a_fresh_queued_request_is_claimed_executed_and_completed(self) -> None:
        clock = FakeClock(datetime(2026, 9, 16, 14, 37, tzinfo=UTC))
        gateway = FakeGateway(new_releases=[_identity(1)])
        request = _queued_request()

        result = run_manual(gateway, clock, request.pk)

        assert result is not None
        self.assertEqual(result.outcome, "succeeded")
        self.assertEqual(result.run.trigger_kind, "manual")
        self.assertIsNone(result.run.scheduled_slot)
        self.assertEqual(gateway.calls, 1)
        request.refresh_from_db()
        self.assertEqual(request.state, "completed")
        self.assertEqual(request.run_id, result.run.pk)
        self.assertIsNotNone(request.claimed_at)
        self.assertIsNotNone(request.completed_at)

    def test_a_terminal_request_is_never_reclaimed(self) -> None:
        clock = FakeClock(datetime(2026, 9, 16, 14, 0, tzinfo=UTC))
        gateway = FakeGateway(new_releases=[_identity(1)])
        request = _queued_request()
        run_manual(gateway, clock, request.pk)
        self.assertEqual(gateway.calls, 1)

        again = run_manual(gateway, clock, request.pk)

        self.assertIsNone(again)  # already "completed"; nothing to do
        self.assertEqual(gateway.calls, 1)  # no re-execution

    def test_a_manual_run_that_loses_the_lease_race_becomes_conflict(self) -> None:
        clock = FakeClock(datetime(2026, 9, 16, 14, 0, tzinfo=UTC))
        request = _queued_request()
        # Something else already holds the ingestion lease (a scheduled tick winning the race).
        other = ProcessingRun.objects.create(trigger_key="scheduled:other", status="running")
        with transaction.atomic():
            acquire_lease(clock, other)

        result = run_manual(FakeGateway(new_releases=[]), clock, request.pk)

        assert result is not None
        self.assertEqual(result.outcome, "skipped_overlap")
        request.refresh_from_db()
        self.assertEqual(request.state, "conflict")
        self.assertEqual(request.reason_code, "busy")
        self.assertEqual(request.run_id, result.run.pk)

    def test_a_crash_after_claim_before_execution_is_resumed_by_the_next_attempt(self) -> None:
        clock = FakeClock(datetime(2026, 9, 16, 14, 0, tzinfo=UTC))
        request = _queued_request()
        # Exactly what the claim step leaves behind if the process is killed immediately after
        # committing "claimed" but before the (separate, longer) execution ever starts.
        stranded_run = ProcessingRun.objects.create(
            trigger_key=f"manual:{request.request_id}",
            status="queued",
            trigger_kind="manual",
        )
        request.state = "claimed"
        request.claimed_at = clock.instant
        request.run = stranded_run
        request.save(update_fields=["state", "claimed_at", "run"])
        gateway = FakeGateway(new_releases=[_identity(1)])

        result = run_manual(gateway, clock, request.pk)

        assert result is not None
        self.assertEqual(result.outcome, "succeeded")
        self.assertEqual(result.run.pk, stranded_run.pk)  # same run, not a second one
        self.assertEqual(ProcessingRun.objects.count(), 1)
        request.refresh_from_db()
        self.assertEqual(request.state, "completed")

    def test_a_genuinely_live_other_owner_leaves_the_request_claimed_for_a_later_tick(
        self,
    ) -> None:
        clock = FakeClock(datetime(2026, 9, 16, 14, 0, tzinfo=UTC))
        request = _queued_request()
        run = ProcessingRun.objects.create(
            trigger_key=f"manual:{request.request_id}",
            status="running",
            business_day=clock.instant.date(),
            trigger_kind="manual",
        )
        with transaction.atomic():
            acquire_lease(clock, run)  # still valid; a real live owner would hold this
        request.state = "claimed"
        request.run = run
        request.save(update_fields=["state", "run"])

        result = run_manual(FakeGateway(new_releases=[]), clock, request.pk)

        self.assertIsNone(result)  # nothing to report yet; the live owner will finish it
        request.refresh_from_db()
        self.assertEqual(request.state, "claimed")  # left untouched, not force-finalized

    def test_an_unknown_or_already_terminal_pk_is_a_no_op(self) -> None:
        clock = FakeClock(datetime(2026, 9, 16, 14, 0, tzinfo=UTC))
        self.assertIsNone(run_manual(FakeGateway(new_releases=[]), clock, 999999))

        expired = _queued_request()
        expired.state = "expired"
        expired.save(update_fields=["state"])
        self.assertIsNone(run_manual(FakeGateway(new_releases=[]), clock, expired.pk))

    def test_a_resumed_run_that_finished_between_lookup_and_resume_reports_its_real_outcome(
        self,
    ) -> None:
        # Only the "running"/resume branch calls `_try_resume` at all (the fresh/"queued" branch
        # races `acquire_lease` directly); this simulates a concurrent resumer finishing for real
        # in the window between this call's initial read and its own resume attempt, matching
        # `test_processing_scheduler.py`'s identical scenario for the scheduled path.
        clock = FakeClock(datetime(2026, 9, 16, 14, 0, tzinfo=UTC))
        request = _queued_request()
        run = ProcessingRun.objects.create(
            trigger_key=f"manual:{request.request_id}",
            status="running",
            business_day=clock.instant.date(),
            trigger_kind="manual",
        )
        with transaction.atomic():
            token = acquire_lease(clock, run)
        run.fencing_token = token
        run.save(update_fields=["fencing_token"])
        request.state = "claimed"
        request.run = run
        request.save(update_fields=["state", "run"])

        def fake_try_resume(run_id: int, gateway: object, tick_clock: object) -> None:
            ProcessingRun.objects.filter(pk=run_id).update(
                status="succeeded", processed_count=1, selected_count=1
            )
            return None

        with patch("processing.scheduler._try_resume", side_effect=fake_try_resume):
            result = run_manual(FakeGateway(new_releases=[]), clock, request.pk)

        assert result is not None
        self.assertEqual(result.outcome, "skipped_duplicate")
        self.assertEqual(result.run.status, "succeeded")
        request.refresh_from_db()
        self.assertEqual(request.state, "completed")
