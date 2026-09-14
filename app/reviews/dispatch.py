"""R14: persist alternation of due review and summary claims across workers/restarts."""

from django.db import transaction
from processing.clock import Clock
from summaries import worker as summary_worker
from summaries.models import SummaryJob

from reviews import collector
from reviews.models import EnrichmentTurn, ReviewCollectionJob


@transaction.atomic
def claim_next(clock: Clock, *, summaries_enabled: bool) -> ReviewCollectionJob | SummaryJob | None:
    EnrichmentTurn.objects.get_or_create(pk=1)
    turn = EnrichmentTurn.objects.select_for_update().get(pk=1)
    kinds = ("summary", "review") if turn.next_kind == "summary" else ("review", "summary")
    for kind in kinds:
        job: ReviewCollectionJob | SummaryJob | None
        if kind == "summary":
            job = summary_worker.claim_next_job(clock) if summaries_enabled else None
        else:
            job = collector.claim_next_job(clock)
        if job is not None:
            turn.next_kind = "summary" if kind == "review" else "review"
            turn.save(update_fields=["next_kind"])
            return job
    return None
