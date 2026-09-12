"""Backlog/oldest-age visibility per `docs/design.md`'s `observability` module and
`research/feasibility/ai-summary.md`'s requirement that IMP-04 record arrivals, cache hits,
completions, outstanding jobs and oldest pending age for the AI job queue — not just claim that a
bounded queue exists. Read-only: computed from persisted `SummaryJob` rows, no separate store.
"""

from __future__ import annotations

from dataclasses import dataclass

from processing.clock import Clock

from summaries.models import SummaryJob

OUTSTANDING_STATES = ("pending", "running", "retryable", "delayed_capacity")
COMPLETED_STATES = ("succeeded", "insufficient_data", "failed")


@dataclass(frozen=True, slots=True)
class BacklogSnapshot:
    arrivals: int
    completed: int
    outstanding: int
    oldest_outstanding_age_seconds: float | None


def backlog_snapshot(clock: Clock) -> BacklogSnapshot:
    now = clock.now_utc()
    arrivals = SummaryJob.objects.count()
    completed = SummaryJob.objects.filter(state__in=COMPLETED_STATES).count()
    outstanding_jobs = SummaryJob.objects.filter(state__in=OUTSTANDING_STATES)
    outstanding = outstanding_jobs.count()
    oldest = outstanding_jobs.exclude(created_at__isnull=True).order_by("created_at").first()
    oldest_age = (now - oldest.created_at).total_seconds() if oldest is not None else None
    return BacklogSnapshot(
        arrivals=arrivals,
        completed=completed,
        outstanding=outstanding,
        oldest_outstanding_age_seconds=oldest_age,
    )
