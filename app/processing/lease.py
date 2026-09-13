"""Singleton `ProcessingLease` acquisition per `SPK-04` `PS-INV-01/02`."""

from datetime import datetime, timedelta

from processing.clock import Clock
from processing.models import ProcessingLease, ProcessingRun

LEASE_TTL = timedelta(minutes=45)
RESOURCE = "ingestion"


class LeaseOverlap(Exception):
    """Another run currently owns the lease and it has not expired."""


class StaleRun(Exception):
    """The lease's fencing token has moved on; this run must not commit further work
    (`PS-INV-02`)."""


def acquire_lease(clock: Clock, run: ProcessingRun) -> int:
    """Must run inside the caller's own `transaction.atomic()` block. Returns the new fencing
    token, or raises `LeaseOverlap` (the row is left untouched in that case)."""
    now = clock.now_utc()
    lease, _ = ProcessingLease.objects.get_or_create(resource=RESOURCE)
    lease = ProcessingLease.objects.select_for_update().get(pk=lease.pk)
    if lease.owner_run_id is not None and lease.expires_at is not None and lease.expires_at > now:
        raise LeaseOverlap(f"lease held by run {lease.owner_run_id} until {lease.expires_at}")
    new_token = lease.fencing_token + 1
    lease.fencing_token = new_token
    lease.owner_run = run
    lease.expires_at = now + LEASE_TTL
    lease.save(update_fields=["fencing_token", "owner_run", "expires_at"])
    return new_token


def release_lease(run: ProcessingRun) -> None:
    """Best-effort release; a crashed run's lease still expires on its own via `expires_at`."""
    ProcessingLease.objects.filter(resource=RESOURCE, owner_run=run).update(
        owner_run=None, expires_at=None
    )


def current_fencing_token() -> int | None:
    lease = ProcessingLease.objects.filter(resource=RESOURCE).first()
    return lease.fencing_token if lease is not None else None


def verify_fencing_token(
    expected_token: int, *, owner_run_id: int | None = None, now: datetime | None = None
) -> None:
    """Must run inside the caller's `transaction.atomic()`; locks the lease row for the rest of
    that transaction so a concurrent reclaim cannot race past this check."""
    lease = ProcessingLease.objects.select_for_update().get(resource=RESOURCE)
    if (
        lease.fencing_token != expected_token
        or (owner_run_id is not None and lease.owner_run_id != owner_run_id)
        or (now is not None and (lease.expires_at is None or lease.expires_at <= now))
    ):
        raise StaleRun(
            f"lease expired or owner changed: token {expected_token}, current {lease.fencing_token}"
        )
