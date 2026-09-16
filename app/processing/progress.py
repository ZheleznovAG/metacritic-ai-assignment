"""BON-21: one counter definition for live views and terminal run records."""

from dataclasses import dataclass

from django.db.models import Count

from processing.models import CoreAttempt


@dataclass(frozen=True)
class RunProgress:
    processed: int = 0
    failed: int = 0
    attempts: int = 0


def progress_for_runs(run_ids: list[int]) -> dict[int, RunProgress]:
    # At most 20 latest candidates per new run, independent of historical attempts.
    latest = (
        CoreAttempt.objects.filter(run_id__in=run_ids)
        .order_by("run_id", "candidate_id", "-attempt_no")
        .distinct("run_id", "candidate_id")
        .values_list("run_id", "outcome")
    )
    totals = {run_id: [0, 0, 0] for run_id in run_ids}
    for run_id, outcome in latest:
        totals[run_id][0] += int(outcome == "succeeded")
        totals[run_id][1] += int(outcome == "failed")
    for row in (
        CoreAttempt.objects.filter(run_id__in=run_ids).values("run_id").annotate(total=Count("id"))
    ):
        totals[row["run_id"]][2] = row["total"]
    return {run_id: RunProgress(*counts) for run_id, counts in totals.items()}
