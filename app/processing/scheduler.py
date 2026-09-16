"""One scheduler tick: trigger dedup, lease acquisition, one batch, run closure.

`docs/design.md`: the scheduler checks the current UTC slot at least once a minute; each tick
here is idempotent per hour via `trigger_key` (`PS-INV-01`).
"""

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from metacritic.gateway import GatewayProtocol

from processing.clock import Clock
from processing.heartbeat import report_progress
from processing.lease import (
    LeaseOverlap,
    StaleRun,
    acquire_lease,
    release_lease,
    verify_fencing_token,
)
from processing.models import CoreAttempt, DailyCandidate, ProcessingRun
from processing.progress import progress_for_runs
from processing.runner import MAX_AUTOMATIC_ATTEMPTS
from processing.selector import run_batch

# A run stuck in one of these states never reached its own final save — either the process
# crashed between creating the row and acquiring the lease (`queued`), or it crashed mid-batch
# after acquiring it (`running`). Neither is a completed outcome (`PS-INV-01` idempotency is
# about not repeating *finished* work), so a later tick for the same hour may safely try to
# resume it, subject to the lease's own liveness check below (HRD-02 / `A05`).
RESUMABLE_STATUSES = ("queued", "running")


@dataclass(frozen=True, slots=True)
class TickResult:
    run: ProcessingRun
    outcome: str


def current_slot(clock: Clock) -> datetime:
    return clock.now_utc().replace(minute=0, second=0, microsecond=0)


def trigger_key_for_slot(slot: datetime) -> str:
    return f"scheduled:{slot.strftime('%Y-%m-%dT%H:00:00Z')}"


def run_tick(gateway: GatewayProtocol, clock: Clock) -> TickResult:
    slot = current_slot(clock)
    trigger_key = trigger_key_for_slot(slot)

    existing = ProcessingRun.objects.filter(trigger_key=trigger_key).first()
    if existing is not None:
        if existing.status in RESUMABLE_STATUSES:
            resumed = _try_resume(existing.pk, gateway, clock)
            if resumed is not None:
                return resumed
            # Someone else (the original owner finishing late, or a concurrent resumer) closed
            # it for real while we were waiting on the row lock; `existing` is now stale — the
            # real outcome/counts already live in the database, not in this in-memory snapshot.
            existing.refresh_from_db()
        return TickResult(run=existing, outcome="skipped_duplicate")

    try:
        run = ProcessingRun.objects.create(
            trigger_key=trigger_key, scheduled_slot=slot, status="queued"
        )
    except IntegrityError:
        # Lost a race to create the same trigger_key; the winner's row is the result.
        winner = ProcessingRun.objects.get(trigger_key=trigger_key)
        if winner.status in RESUMABLE_STATUSES:
            resumed = _try_resume(winner.pk, gateway, clock)
            if resumed is not None:
                return resumed
            winner.refresh_from_db()
        return TickResult(run=winner, outcome="skipped_duplicate")

    try:
        with transaction.atomic():
            token = acquire_lease(clock, run)
    except LeaseOverlap:
        run.status = "skipped_overlap"
        run.save(update_fields=["status"])
        return TickResult(run=run, outcome="skipped_overlap")

    _mark_running(run, token, clock)
    return _execute_and_close(gateway, clock, run, token)


def _try_resume(run_id: int, gateway: GatewayProtocol, clock: Clock) -> TickResult | None:
    """Attempts to take over an existing, not-yet-finished run for this hour. Returns `None`
    (leaving the row untouched) if the lease shows it is still genuinely owned by a live process,
    so the caller falls back to reporting it as a plain duplicate rather than racing a real owner.
    """
    with transaction.atomic():
        run = ProcessingRun.objects.select_for_update().get(pk=run_id)
        if run.status not in RESUMABLE_STATUSES:
            # Another resumer (or the original owner, finishing late) already closed it while we
            # were waiting for this row lock.
            return None
        try:
            token = acquire_lease(clock, run)
        except LeaseOverlap:
            return None
        _mark_running(run, token, clock)
    return _execute_and_close(gateway, clock, run, token)


def _mark_running(run: ProcessingRun, token: int, clock: Clock) -> None:
    now = clock.now_utc()
    run.fencing_token = token
    run.business_day = run.business_day or now.date()  # business timezone = UTC (ASM-01)
    run.started_at = run.started_at or now
    run.status = "running"
    run.save(update_fields=["fencing_token", "business_day", "started_at", "status"])
    report_progress("discovery", run_id=run.pk, deadline_seconds=180)


def _execute_and_close(
    gateway: GatewayProtocol, clock: Clock, run: ProcessingRun, token: int
) -> TickResult:
    try:
        return _execute_owned(gateway, clock, run, token)
    finally:
        release_lease(run, token)


def _save_closure(run: ProcessingRun, fields: list[str], token: int) -> TickResult:
    # A late response from an expired instance must not close a newly resumed instance of
    # this same run, nor replace its counters. The lease and metadata use the same fence.
    ProcessingRun.objects.filter(pk=run.pk, fencing_token=token).update(
        **{field: getattr(run, field) for field in fields}
    )
    run.refresh_from_db()
    return TickResult(run=run, outcome=run.status)


def _execute_owned(
    gateway: GatewayProtocol, clock: Clock, run: ProcessingRun, token: int
) -> TickResult:
    try:
        result = run_batch(gateway, clock, run)
    except StaleRun:
        # Backfill accurate counters from what actually committed before the lease moved
        # on (PS-INV-02) — individual CoreAttempt/DailyCandidate rows are the ground truth
        # even though run_batch never returned a BatchResult in this path.
        counts = progress_for_runs([run.pk])[run.pk]
        processed, failed = counts.processed, counts.failed
        run.selected_count = max(run.selected_count, processed + failed)
        run.processed_count = processed
        run.failed_count = failed
        run.status = "partial" if processed > 0 else "failed"
        run.error_code = "lease_expired"
        run.ended_at = clock.now_utc()
        return _save_closure(
            run,
            [
                "selected_count",
                "processed_count",
                "failed_count",
                "status",
                "error_code",
                "ended_at",
            ],
            token,
        )
    except Exception:
        # Preserve durable diagnostics before surfacing an unexpected programming/runtime
        # error. Expected source failures are classified per candidate and continue the batch.
        try:
            with transaction.atomic():
                verify_fencing_token(token, owner_run_id=run.pk, now=clock.now_utc())
                active = CoreAttempt.objects.filter(run=run, outcome__isnull=True)
                candidate_ids = list(active.values_list("candidate_id", flat=True))
                active.update(
                    outcome="failed", error_code="unexpected_error", ended_at=clock.now_utc()
                )
                candidates = DailyCandidate.objects.filter(pk__in=candidate_ids, state="processing")
                candidates.filter(attempt_count__lt=MAX_AUTOMATIC_ATTEMPTS).update(
                    state="retryable", last_error="unexpected_error"
                )
                candidates.filter(attempt_count__gte=MAX_AUTOMATIC_ATTEMPTS).update(
                    state="failed", last_error="unexpected_error"
                )
        except StaleRun:
            pass  # Another owner decides recovery; this run can only close its own metadata.
        run.refresh_from_db(fields=["selected_count"])
        counts = progress_for_runs([run.pk])[run.pk]
        run.processed_count, run.failed_count = counts.processed, counts.failed
        run.status = "partial" if run.processed_count else "failed"
        run.error_code = "unexpected_error"
        run.ended_at = clock.now_utc()
        _save_closure(
            run,
            [
                "processed_count",
                "failed_count",
                "status",
                "error_code",
                "ended_at",
            ],
            token,
        )
        raise

    run.selected_count = result.selected_count
    run.processed_count = result.processed_count
    run.failed_count = result.failed_count
    run.status = result.status
    run.error_code = result.error_code
    run.ended_at = clock.now_utc()
    return _save_closure(
        run,
        [
            "selected_count",
            "processed_count",
            "failed_count",
            "status",
            "error_code",
            "ended_at",
        ],
        token,
    )
