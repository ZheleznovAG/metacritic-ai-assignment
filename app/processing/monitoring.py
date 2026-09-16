"""BON-21: bounded public projection, read from one committed PostgreSQL snapshot."""

from datetime import datetime
from typing import Any

from django.db import connection, transaction
from django.db.models import Count, Min, QuerySet
from reviews.models import ReviewCollectionJob
from summaries.models import SummaryJob

from processing.clock import Clock, SystemClock
from processing.heartbeat import process_state
from processing.models import DailyCandidate, ProcessHeartbeat, ProcessingLease, ProcessingRun
from processing.progress import progress_for_runs

HISTORY_LIMIT = 20
STAGES = {
    "idle": "Waiting for work",
    "scheduler_check": "Checking hourly schedule",
    "discovery": "Discovering games",
    "core": "Processing game",
    "claiming": "Checking queues",
    "reviews": "Collecting reviews",
    "summary": "Generating summary",
    "source_request": "Reading Metacritic",
    "saving": "Saving results",
    "stopped": "Stopped",
}
PUBLIC_ERRORS = {
    "legacy_batch_unavailable",
    "lease_expired",
    "unexpected_error",
    "new_releases_failed",
    "browse_fetch_failed",
    "browse_page_limit",
    "browse_time_limit",
    "browse_repeated_page",
    "browse_empty_page",
    "http_403",
    "http_429",
    "http_500",
    "http_502",
    "http_503",
    "http_504",
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="milliseconds") if value is not None else None


def _age(value: datetime | None, now: datetime) -> int | None:
    return max(0, int((now - value).total_seconds())) if value is not None else None


def _queue(
    jobs: QuerySet[Any],
    choices: list[tuple[str, str]],
    terminal: set[str],
    now: datetime,
) -> dict[str, Any]:
    rows = list(jobs.values("state").annotate(count=Count("id"), oldest=Min("created_at")))
    states = {state: 0 for state, _ in choices}
    oldest = None
    for row in rows:
        if row["state"] in states:
            states[row["state"]] = row["count"]
        if row["state"] not in terminal and row["oldest"] is not None:
            oldest = min(oldest, row["oldest"]) if oldest else row["oldest"]
    return {
        "states": states,
        "oldest_wait_seconds": _age(oldest, now),
        "outstanding": sum(count for state, count in states.items() if state not in terminal),
    }


def _snapshot(clock: Clock) -> dict[str, Any]:
    now = clock.now_utc()
    lease = ProcessingLease.objects.filter(resource="ingestion").first()
    runs = list(ProcessingRun.objects.order_by("-id")[:HISTORY_LIMIT])
    active_id = lease.owner_run_id if lease else None
    if active_id and all(run.pk != active_id for run in runs):
        active = ProcessingRun.objects.filter(pk=active_id).first()
        if active:
            runs.append(active)
    counts = progress_for_runs([run.pk for run in runs])
    run_data = []
    for run in runs:
        count = counts[run.pk]
        live = run.status in {"queued", "running"}
        run_data.append(
            {
                "id": run.pk,
                "status": run.status,
                "selected": run.selected_count,
                "processed": count.processed if live else run.processed_count,
                "failed": count.failed if live else run.failed_count,
                "attempts": count.attempts,
                "started_at": _iso(run.started_at),
                "ended_at": _iso(run.ended_at),
                "business_day": run.business_day.isoformat() if run.business_day else None,
                "scheduled_slot": _iso(run.scheduled_slot),
                "error": (run.error_code if run.error_code in PUBLIC_ERRORS else "processing_error")
                if run.error_code
                else None,
            }
        )
    by_role = {
        row.role: row
        for row in ProcessHeartbeat.objects.filter(slot="main", role__in=("scheduler", "worker"))
    }
    processes = []
    for role in ("scheduler", "worker"):
        row = by_role.get(role)
        processes.append(
            {
                "role": role,
                "label": "Scheduler" if role == "scheduler" else "Reviews & AI worker",
                "status": process_state(row.last_seen_at, row.mode, now) if row else "unknown",
                "stage": STAGES.get(row.stage, "Working") if row else "No heartbeat received",
                "last_seen_at": _iso(row.last_seen_at) if row else None,
                "last_progress_at": _iso(row.last_progress_at) if row else None,
                "progress_age_seconds": _age(row.last_progress_at, now) if row else None,
                "run_id": row.run_id if row else None,
                "job_id": row.job_id if row else None,
                "overdue": bool(
                    row and row.mode == "busy" and row.deadline_at and row.deadline_at < now
                ),
            }
        )
    day_counts = {state: 0 for state, _ in DailyCandidate.STATE_CHOICES}
    day_counts.update(
        dict(
            DailyCandidate.objects.filter(cycle__business_date=now.date(), cycle__timezone="UTC")
            .values("state")
            .annotate(count=Count("id"))
            .values_list("state", "count")
        )
    )
    return {
        "snapshot_at": _iso(now),
        "business_day": now.date().isoformat(),
        "timezone": "UTC",
        "processes": processes,
        "history": run_data[:HISTORY_LIMIT],
        "active_run": next((run for run in run_data if run["id"] == active_id), None),
        "lease_expired": bool(active_id and lease and lease.expires_at and lease.expires_at <= now),
        "today": {"found": sum(day_counts.values()), "states": day_counts},
        "reviews": _queue(
            ReviewCollectionJob.objects.all(),
            ReviewCollectionJob.STATE_CHOICES,
            {"complete", "empty"},
            now,
        ),
        "summaries": _queue(
            SummaryJob.objects.all(),
            SummaryJob.STATE_CHOICES,
            {"succeeded", "insufficient_data"},
            now,
        ),
    }


def snapshot(clock: Clock | None = None) -> dict[str, Any]:
    # Requests are not wrapped in ATOMIC_REQUESTS. Refuse a nested transaction rather than
    # silently making a READ COMMITTED collection of queries look like a consistent snapshot.
    if connection.in_atomic_block:
        raise RuntimeError("Monitoring requires its own read-only transaction")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = 800")
        return _snapshot(clock or SystemClock())
