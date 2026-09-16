"""BON-22: durable admission for browser-triggered manual runs (`docs/bonus2_design.md`).

Web never locks `ProcessingLease` (it holds only `SELECT` there); this module's transaction
locks `TriggerAdmission` (a singleton row, the same idiom as `ProcessingLease`) and the
`ManualRunRequest` rows it protects, then commits -- before any lease is ever touched by the
scheduler's dispatcher. That fixed order (admission -> request/run, never -> lease from this
side) avoids a deadlock between concurrent web admission and scheduler execution.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction

from processing.clock import Clock
from processing.models import ManualRunRequest, ProcessingLease, TriggerAdmission

RESOURCE = "manual_trigger"


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    outcome: str  # "accepted" | "replayed" | "busy" | "rate_limited"
    request: ManualRunRequest | None = None
    active_run_id: int | None = None
    retry_after_seconds: int | None = None


class AdmissionConflict(Exception):
    """`request_id` already belongs to a different operator; never disclose whose."""


def admit(operator: User, request_id: uuid.UUID, clock: Clock) -> AdmissionResult:
    """Idempotency is checked before busy/rate limits (a replayed key never spends quota)."""
    now = clock.now_utc()
    with transaction.atomic():
        # The singleton row is seeded by a migration (RunPython, under the migrate role) so web
        # -- which only ever gets a narrow `UPDATE` grant here, never `INSERT` -- can lock it
        # without needing to create it.
        TriggerAdmission.objects.select_for_update().get(resource=RESOURCE)

        existing = ManualRunRequest.objects.filter(request_id=request_id).first()
        if existing is not None:
            if existing.operator_id != operator.pk:
                raise AdmissionConflict("request_id already used by a different operator")
            return AdmissionResult(outcome="replayed", request=existing)

        # Advisory-only: web has no write access to ProcessingLease, so this is a plain read
        # subject to the same race any two concurrent triggers can have; the dispatcher's own
        # lease acquisition is the real, race-free enforcement -- a request accepted here can
        # still end up "conflict" if a scheduled slot wins that race a moment later.
        lease = ProcessingLease.objects.filter(resource="ingestion").first()
        if lease and lease.owner_run_id and lease.expires_at and lease.expires_at > now:
            return AdmissionResult(outcome="busy", active_run_id=lease.owner_run_id)

        window_start = now - timedelta(hours=1)
        recent = list(
            ManualRunRequest.objects.filter(created_at__gte=window_start).order_by("-created_at")
        )
        if recent:
            since_last = (now - recent[0].created_at).total_seconds()
            if since_last < settings.MANUAL_RUN_COOLDOWN_SECONDS:
                retry = settings.MANUAL_RUN_COOLDOWN_SECONDS - int(since_last)
                return AdmissionResult(outcome="rate_limited", retry_after_seconds=max(1, retry))
        if len(recent) >= settings.MANUAL_RUN_HOURLY_LIMIT:
            oldest = recent[-1].created_at
            retry = int((oldest + timedelta(hours=1) - now).total_seconds())
            return AdmissionResult(outcome="rate_limited", retry_after_seconds=max(1, retry))

        request = ManualRunRequest.objects.create(
            request_id=request_id, operator=operator, created_at=now
        )
        return AdmissionResult(outcome="accepted", request=request)


def lookup(request_id: uuid.UUID, operator: User) -> ManualRunRequest | None:
    """Restricted to the requesting operator's own requests; never used by the public snapshot."""
    return ManualRunRequest.objects.filter(request_id=request_id, operator=operator).first()


def expire_stale(clock: Clock, queue_ttl: timedelta) -> None:
    """A queued request that no dispatcher claims within `queue_ttl` expires lazily: after a
    long idle stretch, a sudden late claim does not surprise-run for a since-departed operator.
    """
    cutoff = clock.now_utc() - queue_ttl
    ManualRunRequest.objects.filter(state="queued", created_at__lt=cutoff).update(
        state="expired", reason_code="queue_timeout"
    )
