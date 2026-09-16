"""BON-22: `processing.admission.admit` -- idempotency-first, then the advisory busy check, then
the rate limit, all under the `TriggerAdmission` singleton lock."""

import uuid
from datetime import UTC, datetime, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase, override_settings
from processing import admission
from processing.admission import AdmissionConflict
from processing.lease import acquire_lease
from processing.models import ManualRunRequest, ProcessingRun, TriggerAdmission

from tests.test_processing_scheduler import FakeClock

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=UTC)


def _operator(name: str = "op") -> User:
    return get_user_model().objects.create_user(username=name, password="x" * 12)


class AdmissionTests(TestCase):
    def setUp(self) -> None:
        TriggerAdmission.objects.get_or_create(resource="manual_trigger")

    def test_a_fresh_key_is_accepted_and_persisted(self) -> None:
        operator = _operator()
        key = uuid.uuid4()

        result = admission.admit(operator, key, FakeClock(NOW))

        self.assertEqual(result.outcome, "accepted")
        assert result.request is not None
        self.assertEqual(result.request.request_id, key)
        self.assertEqual(result.request.operator_id, operator.pk)
        self.assertEqual(result.request.state, "queued")

    def test_replaying_the_same_key_by_the_same_operator_returns_the_same_request(self) -> None:
        operator = _operator()
        key = uuid.uuid4()
        first = admission.admit(operator, key, FakeClock(NOW))

        second = admission.admit(operator, key, FakeClock(NOW + timedelta(seconds=1)))

        self.assertEqual(second.outcome, "replayed")
        assert first.request is not None and second.request is not None
        self.assertEqual(second.request.pk, first.request.pk)
        self.assertEqual(ManualRunRequest.objects.count(), 1)

    def test_a_replay_never_spends_the_rate_limit(self) -> None:
        operator = _operator()
        key = uuid.uuid4()
        admission.admit(operator, key, FakeClock(NOW))

        for _ in range(10):
            result = admission.admit(operator, key, FakeClock(NOW + timedelta(seconds=1)))
            self.assertEqual(result.outcome, "replayed")

    def test_the_same_key_from_a_different_operator_is_a_conflict_without_disclosure(self) -> None:
        first_operator = _operator("first")
        second_operator = _operator("second")
        key = uuid.uuid4()
        admission.admit(first_operator, key, FakeClock(NOW))

        with self.assertRaises(AdmissionConflict):
            admission.admit(second_operator, key, FakeClock(NOW))

    def test_an_active_lease_makes_a_new_key_busy(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        run = ProcessingRun.objects.create(trigger_key="scheduled:x", status="running")
        with transaction.atomic():
            acquire_lease(clock, run)

        result = admission.admit(operator, uuid.uuid4(), clock)

        self.assertEqual(result.outcome, "busy")
        self.assertEqual(result.active_run_id, run.pk)
        self.assertEqual(ManualRunRequest.objects.count(), 0)  # no request persisted

    def test_an_expired_lease_does_not_count_as_busy(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        run = ProcessingRun.objects.create(trigger_key="scheduled:x", status="running")
        with transaction.atomic():
            acquire_lease(clock, run)
        clock.instant += timedelta(hours=1)  # well past LEASE_TTL

        result = admission.admit(operator, uuid.uuid4(), clock)

        self.assertEqual(result.outcome, "accepted")

    @override_settings(MANUAL_RUN_COOLDOWN_SECONDS=300, MANUAL_RUN_HOURLY_LIMIT=6)
    def test_a_second_request_inside_the_cooldown_is_rate_limited(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        admission.admit(operator, uuid.uuid4(), clock)

        clock.instant += timedelta(seconds=60)
        result = admission.admit(operator, uuid.uuid4(), clock)

        self.assertEqual(result.outcome, "rate_limited")
        self.assertEqual(result.retry_after_seconds, 240)
        self.assertEqual(ManualRunRequest.objects.count(), 1)

    @override_settings(MANUAL_RUN_COOLDOWN_SECONDS=0, MANUAL_RUN_HOURLY_LIMIT=6)
    def test_the_seventh_request_within_an_hour_is_rate_limited(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        for _ in range(6):
            result = admission.admit(operator, uuid.uuid4(), clock)
            self.assertEqual(result.outcome, "accepted")
            clock.instant += timedelta(seconds=1)

        result = admission.admit(operator, uuid.uuid4(), clock)

        self.assertEqual(result.outcome, "rate_limited")
        assert result.retry_after_seconds is not None
        self.assertGreater(result.retry_after_seconds, 0)

    @override_settings(MANUAL_RUN_COOLDOWN_SECONDS=0, MANUAL_RUN_HOURLY_LIMIT=6)
    def test_requests_outside_the_trailing_hour_do_not_count_toward_the_limit(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        for _ in range(6):
            admission.admit(operator, uuid.uuid4(), clock)
            clock.instant += timedelta(seconds=1)
        clock.instant += timedelta(hours=1)

        result = admission.admit(operator, uuid.uuid4(), clock)

        self.assertEqual(result.outcome, "accepted")


class ExpireStaleTests(TestCase):
    def test_a_queued_request_past_the_ttl_expires(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        request = ManualRunRequest.objects.create(
            request_id=uuid.uuid4(), operator=operator, created_at=NOW
        )
        clock.instant += timedelta(minutes=6)

        admission.expire_stale(clock, timedelta(minutes=5))

        request.refresh_from_db()
        self.assertEqual(request.state, "expired")
        self.assertEqual(request.reason_code, "queue_timeout")

    def test_a_claimed_request_never_expires_this_way(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        request = ManualRunRequest.objects.create(
            request_id=uuid.uuid4(), operator=operator, state="claimed", created_at=NOW
        )
        clock.instant += timedelta(minutes=6)

        admission.expire_stale(clock, timedelta(minutes=5))

        request.refresh_from_db()
        self.assertEqual(request.state, "claimed")

    def test_a_fresh_queued_request_does_not_expire_early(self) -> None:
        operator = _operator()
        clock = FakeClock(NOW)
        request = ManualRunRequest.objects.create(
            request_id=uuid.uuid4(), operator=operator, created_at=NOW
        )
        clock.instant += timedelta(minutes=4)

        admission.expire_stale(clock, timedelta(minutes=5))

        request.refresh_from_db()
        self.assertEqual(request.state, "queued")
