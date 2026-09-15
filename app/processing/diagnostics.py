"""HRD-05: by-ID diagnostics over persisted run/game/job state, per `docs/design.md`'s
`observability` component contract ("Structured events и представление persistent run/job
state" -- not a separate storage/monitoring service). Every function is a read-only query
returning a JSON-serializable dict; no new tables, no separate event store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from catalog.models import Game
from django.db.models import Count
from reviews.models import ReviewCollectionJob
from summaries import observability
from summaries.models import SummaryJob

from processing.clock import Clock
from processing.models import DailyCandidate, ProcessingRun


def _iso(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else None


def run_diagnostics(run_id: int) -> dict[str, Any] | None:
    """Success, error, and processed/failed/selected counts for one scheduler run."""
    run = ProcessingRun.objects.filter(pk=run_id).first()
    if run is None:
        return None
    return {
        "run_id": run.id,
        "trigger_key": run.trigger_key,
        "status": run.status,
        "error_code": run.error_code,
        "business_day": run.business_day.isoformat() if run.business_day else None,
        "started_at": _iso(run.started_at),
        "ended_at": _iso(run.ended_at),
        "selected_count": run.selected_count,
        "processed_count": run.processed_count,
        "failed_count": run.failed_count,
    }


def game_diagnostics(game_id: int) -> dict[str, Any] | None:
    """Per-game rollup: latest daily-candidate outcome (with its own last success), plus every
    review-collection and summary job's own state/error -- the union `HRD-05` asks be diagnosable
    for one game, without a separate Bonus UI."""
    game = Game.objects.filter(pk=game_id).first()
    if game is None:
        return None
    candidates = DailyCandidate.objects.filter(game=game).select_related("cycle")
    latest_candidate = candidates.order_by("-cycle__business_date", "-id").first()
    last_processed = (
        candidates.filter(state="processed").order_by("-cycle__business_date", "-id").first()
    )
    review_jobs = [
        {
            "job_id": job.id,
            "platform_slug": job.game_platform.slug,
            "audience": job.audience,
            "state": job.state,
            "last_error": job.last_error,
            "fetched_count": job.fetched_count,
            "unique_count": job.unique_count,
            "completed_at": _iso(job.completed_at),
        }
        for job in ReviewCollectionJob.objects.filter(game_platform__game=game).select_related(
            "game_platform"
        )
    ]
    summary_jobs = [
        {
            "job_id": job.id,
            "audience": job.audience,
            "state": job.state,
            "last_error": job.last_error,
            "attempt_count": job.attempt_count,
        }
        for job in SummaryJob.objects.filter(game=game)
    ]
    return {
        "game_id": game.id,
        "title": game.title,
        "latest_candidate_state": latest_candidate.state if latest_candidate else None,
        "latest_candidate_last_error": latest_candidate.last_error if latest_candidate else None,
        "last_success_business_date": (
            last_processed.cycle.business_date.isoformat() if last_processed else None
        ),
        "review_jobs": review_jobs,
        "summary_jobs": summary_jobs,
    }


def _review_job_diagnostics(job_id: int) -> dict[str, Any] | None:
    job = ReviewCollectionJob.objects.filter(pk=job_id).select_related("game_platform").first()
    if job is None:
        return None
    return {
        "kind": "review",
        "job_id": job.id,
        "game_id": job.game_platform.game_id,
        "audience": job.audience,
        "state": job.state,
        "last_error": job.last_error,
        "attempt_count": job.attempt_count,
        "fetched_count": job.fetched_count,
        "unique_count": job.unique_count,
        "page_count": job.page_count,
        "completed_at": _iso(job.completed_at),
    }


def _summary_job_diagnostics(job_id: int) -> dict[str, Any] | None:
    job = SummaryJob.objects.filter(pk=job_id).first()
    if job is None:
        return None
    return {
        "kind": "summary",
        "job_id": job.id,
        "game_id": job.game_id,
        "audience": job.audience,
        "state": job.state,
        "last_error": job.last_error,
        "attempt_count": job.attempt_count,
    }


def job_diagnostics(kind: str, job_id: int) -> dict[str, Any] | None:
    """One review-collection or summary job's own state/error/attempt history."""
    if kind == "review":
        return _review_job_diagnostics(job_id)
    if kind == "summary":
        return _summary_job_diagnostics(job_id)
    raise ValueError(f"unknown job kind {kind!r}; expected 'review' or 'summary'")


def backlog_diagnostics(clock: Clock) -> dict[str, Any]:
    """Full state breakdown across the whole pipeline, by stage -- not just the AI queue that
    `summaries.observability.backlog_snapshot` already covers. Every state is reported for both
    `DailyCandidate` and `ReviewCollectionJob` (not just a filtered "outstanding" subset): a
    `ReviewCollectionJob` can be stuck `unstable` or `failed` -- `reviews/collector.py` documents
    that such a job "stays visible and diagnosable" rather than being auto-restarted -- and this
    is exactly that diagnosable surface, so it must not be silently excluded the way an
    outstanding-only filter would."""
    candidate_by_state = dict(
        DailyCandidate.objects.values("state")
        .annotate(count=Count("id"))
        .values_list("state", "count")
    )
    review_by_state = dict(
        ReviewCollectionJob.objects.values("state")
        .annotate(count=Count("id"))
        .values_list("state", "count")
    )
    summary_snapshot = observability.backlog_snapshot(clock)
    return {
        "daily_candidates_by_state": candidate_by_state,
        "review_jobs_by_state": review_by_state,
        "summary_backlog": {
            "arrivals": summary_snapshot.arrivals,
            "completed": summary_snapshot.completed,
            "outstanding": summary_snapshot.outstanding,
            "oldest_outstanding_age_seconds": summary_snapshot.oldest_outstanding_age_seconds,
        },
    }
