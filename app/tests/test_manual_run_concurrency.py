"""BON-22 / HRD-03-style: the sequential coverage in `test_admission.py`/`test_manual_run.py`
proves the *logic* is correct given a known interleaving; these use real threads with their own
DB connections and a `threading.Barrier` (`tests.concurrency.run_concurrently`) to prove the
underlying `select_for_update()` locks actually serialize genuinely concurrent PostgreSQL
transactions, which a single-connection `TestCase` can never exercise.
"""

import uuid
from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TransactionTestCase, override_settings
from processing import admission
from processing.models import ManualRunRequest, TriggerAdmission
from processing.scheduler import run_manual

from tests.concurrency import run_concurrently
from tests.test_processing_scheduler import FakeClock, FakeGateway, _identity

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)


class AdmissionRaceTests(TransactionTestCase):
    def test_two_real_threads_replaying_the_same_key_never_both_create_a_request(self) -> None:
        operator = get_user_model().objects.create_user(username="op", password="x" * 12)
        TriggerAdmission.objects.get_or_create(resource="manual_trigger")
        key = uuid.uuid4()

        def attempt() -> str:
            try:
                return admission.admit(operator, key, FakeClock(NOW)).outcome
            finally:
                connections.close_all()

        outcomes, errors = run_concurrently(attempt, attempt)

        self.assertEqual(errors, [], f"admit() raised under real concurrency: {errors}")
        self.assertEqual(sorted(outcomes), ["accepted", "replayed"])
        self.assertEqual(ManualRunRequest.objects.count(), 1)

    @override_settings(MANUAL_RUN_COOLDOWN_SECONDS=0, MANUAL_RUN_HOURLY_LIMIT=1)
    def test_two_real_threads_racing_for_the_last_hourly_slot_never_both_win(self) -> None:
        operator = get_user_model().objects.create_user(username="op", password="x" * 12)
        TriggerAdmission.objects.get_or_create(resource="manual_trigger")

        def attempt() -> str:
            try:
                return admission.admit(operator, uuid.uuid4(), FakeClock(NOW)).outcome
            finally:
                connections.close_all()

        outcomes, errors = run_concurrently(attempt, attempt)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(outcomes), ["accepted", "rate_limited"])
        self.assertEqual(ManualRunRequest.objects.count(), 1)


class DispatcherRaceTests(TransactionTestCase):
    def test_two_real_threads_claiming_the_same_manual_request_never_both_execute(self) -> None:
        operator = get_user_model().objects.create_user(username="op", password="x" * 12)
        request = ManualRunRequest.objects.create(
            request_id=uuid.uuid4(), operator=operator, created_at=NOW
        )
        gateway = FakeGateway(new_releases=[_identity(1)])

        def attempt() -> object:
            try:
                return run_manual(gateway, FakeClock(NOW), request.pk)
            finally:
                connections.close_all()

        results, errors = run_concurrently(attempt, attempt)

        self.assertEqual(errors, [], f"run_manual raised under real concurrency: {errors}")
        self.assertEqual(gateway.calls, 1, "exactly one racer must actually execute the batch")
        winners = [r for r in results if r is not None]
        self.assertEqual(len(winners), 1)
        request.refresh_from_db()
        self.assertEqual(request.state, "completed")
