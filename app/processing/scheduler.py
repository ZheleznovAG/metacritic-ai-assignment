"""One scheduler tick: trigger dedup, lease acquisition, one batch, run closure.

`docs/design.md`: the scheduler checks the current UTC slot at least once a minute; each tick
here is idempotent per hour via `trigger_key` (`PS-INV-01`).
"""

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from metacritic.gateway import GatewayProtocol

from processing.clock import Clock
from processing.lease import (
    LeaseOverlap,
    StaleRun,
    acquire_lease,
    release_lease,
    verify_fencing_token,
)
from processing.models import CoreAttempt, DailyCandidate, ProcessingRun
from processing.runner import MAX_AUTOMATIC_ATTEMPTS
from processing.selector import run_batch


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
        return TickResult(run=existing, outcome="skipped_duplicate")

    try:
        run = ProcessingRun.objects.create(
            trigger_key=trigger_key, scheduled_slot=slot, status="queued"
        )
    except IntegrityError:
        # Lost a race to create the same trigger_key; the winner's row is the result.
        winner = ProcessingRun.objects.get(trigger_key=trigger_key)
        return TickResult(run=winner, outcome="skipped_duplicate")

    try:
        with transaction.atomic():
            token = acquire_lease(clock, run)
    except LeaseOverlap:
        run.status = "skipped_overlap"
        run.save(update_fields=["status"])
        return TickResult(run=run, outcome="skipped_overlap")

    now = clock.now_utc()
    run.fencing_token = token
    run.business_day = now.date()  # business timezone = UTC (ASM-01)
    run.started_at = now
    run.status = "running"
    run.save(update_fields=["fencing_token", "business_day", "started_at", "status"])

    try:
        try:
            result = run_batch(gateway, clock, run)
        except StaleRun:
            # Backfill accurate counters from what actually committed before the lease moved
            # on (PS-INV-02) — individual CoreAttempt/DailyCandidate rows are the ground truth
            # even though run_batch never returned a BatchResult in this path.
            processed = CoreAttempt.objects.filter(run=run, outcome="succeeded").count()
            failed = CoreAttempt.objects.filter(run=run, outcome="failed").count()
            run.selected_count = max(run.selected_count, processed + failed)
            run.processed_count = processed
            run.failed_count = failed
            run.status = "partial" if processed > 0 else "failed"
            run.error_code = "lease_expired"
            run.ended_at = clock.now_utc()
            run.save(
                update_fields=[
                    "selected_count",
                    "processed_count",
                    "failed_count",
                    "status",
                    "error_code",
                    "ended_at",
                ]
            )
            return TickResult(run=run, outcome=run.status)
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
                    candidates = DailyCandidate.objects.filter(
                        pk__in=candidate_ids, state="processing"
                    )
                    candidates.filter(attempt_count__lt=MAX_AUTOMATIC_ATTEMPTS).update(
                        state="retryable", last_error="unexpected_error"
                    )
                    candidates.filter(attempt_count__gte=MAX_AUTOMATIC_ATTEMPTS).update(
                        state="failed", last_error="unexpected_error"
                    )
            except StaleRun:
                pass  # Another owner decides recovery; this run can only close its own metadata.
            run.refresh_from_db(fields=["selected_count"])
            run.processed_count = CoreAttempt.objects.filter(run=run, outcome="succeeded").count()
            run.failed_count = CoreAttempt.objects.filter(run=run, outcome="failed").count()
            run.status = "partial" if run.processed_count else "failed"
            run.error_code = "unexpected_error"
            run.ended_at = clock.now_utc()
            run.save(
                update_fields=[
                    "processed_count",
                    "failed_count",
                    "status",
                    "error_code",
                    "ended_at",
                ]
            )
            raise
    finally:
        release_lease(run)

    run.selected_count = result.selected_count
    run.processed_count = result.processed_count
    run.failed_count = result.failed_count
    run.status = result.status
    run.error_code = result.error_code
    run.ended_at = clock.now_utc()
    run.save(
        update_fields=[
            "selected_count",
            "processed_count",
            "failed_count",
            "status",
            "error_code",
            "ended_at",
        ]
    )
    return TickResult(run=run, outcome=result.status)
