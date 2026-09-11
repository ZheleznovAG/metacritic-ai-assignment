"""One scheduler tick: trigger dedup, lease acquisition, one batch, run closure.

`docs/design.md`: the scheduler checks the current UTC slot at least once a minute; each tick
here is idempotent per hour via `trigger_key` (`PS-INV-01`).
"""

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from metacritic.gateway import GatewayProtocol

from processing.clock import Clock
from processing.lease import LeaseOverlap, StaleRun, acquire_lease, release_lease
from processing.models import CoreAttempt, ProcessingRun
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
            run.selected_count = processed + failed
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
    finally:
        release_lease(run)

    run.selected_count = result.selected_count
    run.processed_count = result.processed_count
    run.failed_count = result.failed_count
    run.status = result.status
    run.ended_at = clock.now_utc()
    run.save(
        update_fields=[
            "selected_count",
            "processed_count",
            "failed_count",
            "status",
            "ended_at",
        ]
    )
    return TickResult(run=run, outcome=result.status)
