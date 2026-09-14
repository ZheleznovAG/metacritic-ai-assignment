"""Read-only summary view for the public card: honest pending/stale/insufficient states, per
`docs/design.md` ("Card показывает последний валидный summary; если current input/config... уже
имеет pending/error job, старый результат помечается stale с причиной"). Never shows raw reviews.
"""

from dataclasses import dataclass

from catalog.models import Game
from reviews.models import ReviewCorpus, ReviewCorpusHead
from reviews.snapshots import collection_state
from summaries.contour import contour_fingerprint
from summaries.models import ReviewSummary, SummaryJob

AUDIENCES = ("critic", "user")


@dataclass(frozen=True, slots=True)
class ClaimView:
    text: str


@dataclass(frozen=True, slots=True)
class SummaryView:
    audience: str
    state: str  # "ok" | "insufficient_data" | "pending" | "stale"
    likes: list[ClaimView]
    dislikes: list[ClaimView]
    model_id: str | None
    generated_at_utc: str | None
    selected_count: int | None
    fetched_count: int | None
    reported_count: int | None
    stale_reason: str | None
    insufficient_data: bool = False

    @property
    def stale_message(self) -> str:
        return {
            "collection_in_progress": "New reviews are being collected.",
            "collection_retryable": "Review collection is waiting for a retry.",
            "collection_failed": "The latest review collection failed.",
            "collection_unstable": "The source changed during review collection.",
            "collection_unverified": "The latest collection has not been verified yet.",
            "contour_changed": "A summary using the current settings is not ready yet.",
            "pending": "An updated summary is waiting to be generated.",
            "running": "An updated summary is being generated.",
            "retryable": "The summary update is waiting for a retry.",
            "delayed_capacity": "The summary update is waiting for provider capacity.",
            "failed": "The latest summary update failed.",
        }.get(self.stale_reason or "", "An updated summary is not ready yet.")


def _empty(audience: str) -> SummaryView:
    return SummaryView(
        audience=audience,
        state="pending",
        likes=[],
        dislikes=[],
        model_id=None,
        generated_at_utc=None,
        selected_count=None,
        fetched_count=None,
        reported_count=None,
        stale_reason=None,
    )


def _view_from_summary(
    summary: ReviewSummary,
    corpus: ReviewCorpus,
    audience: str,
    *,
    state: str,
    stale_reason: str | None,
) -> SummaryView:
    likes = [
        ClaimView(text=claim.claim)
        for claim in summary.claims.filter(polarity="like").order_by("ordinal")
    ]
    dislikes = [
        ClaimView(text=claim.claim)
        for claim in summary.claims.filter(polarity="dislike").order_by("ordinal")
    ]
    model_id = summary.successful_attempt.returned_model if summary.successful_attempt else None
    return SummaryView(
        audience=audience,
        state=state,
        likes=likes,
        dislikes=dislikes,
        model_id=model_id,
        generated_at_utc=summary.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        selected_count=corpus.selected_count,
        fetched_count=corpus.fetched_count,
        reported_count=corpus.reported_count,
        stale_reason=stale_reason,
        insufficient_data=summary.status == "insufficient_data",
    )


def _summary_view(game: Game, audience: str) -> SummaryView:
    collection = collection_state(game, audience)
    head = (
        ReviewCorpusHead.objects.filter(game=game, audience=audience)
        .select_related("corpus")
        .first()
    )
    latest_corpus = head.corpus if head else None
    reason = collection.reason
    if reason is None and (head is None or head.collection_checkpoint != collection.checkpoint):
        reason = "collection_unverified"
    current_job = None
    if latest_corpus is not None and reason is None:
        current_job = SummaryJob.objects.filter(
            game=game,
            audience=audience,
            input_fingerprint=latest_corpus.model_input_fingerprint,
            contour_fingerprint=contour_fingerprint(),
        ).first()
        if current_job is not None and current_job.state in ("succeeded", "insufficient_data"):
            current_summary = getattr(current_job, "summary", None)
            if current_summary is not None:
                state = "ok" if current_summary.status == "ok" else "insufficient_data"
                return _view_from_summary(
                    current_summary, latest_corpus, audience, state=state, stale_reason=None
                )
        reason = current_job.state if current_job else "contour_changed"

    stale_summary = (
        ReviewSummary.objects.filter(job__game=game, job__audience=audience)
        .select_related("job__source_corpus")
        .order_by("-generated_at", "-id")
        .first()
    )
    if stale_summary is None:
        return _empty(audience)
    return _view_from_summary(
        stale_summary, stale_summary.job.source_corpus, audience, state="stale", stale_reason=reason
    )


def get_summaries(game: Game) -> list[SummaryView]:
    return [_summary_view(game, audience) for audience in AUDIENCES]
