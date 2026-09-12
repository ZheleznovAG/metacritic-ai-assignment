"""Read-only summary view for the public card: honest pending/stale/insufficient states, per
`docs/design.md` ("Card показывает последний валидный summary; если current input/config... уже
имеет pending/error job, старый результат помечается stale с причиной"). Never shows raw reviews.
"""

from dataclasses import dataclass

from catalog.models import Game
from reviews.models import ReviewCorpus
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
    )


def _summary_view(game: Game, audience: str) -> SummaryView:
    latest_corpus = (
        ReviewCorpus.objects.filter(game=game, audience=audience).order_by("-created_at").first()
    )
    current_job = None
    if latest_corpus is not None:
        current_job = SummaryJob.objects.filter(source_corpus=latest_corpus).order_by("-id").first()
        if current_job is not None and current_job.state in ("succeeded", "insufficient_data"):
            current_summary = getattr(current_job, "summary", None)
            if current_summary is not None:
                state = "ok" if current_summary.status == "ok" else "insufficient_data"
                return _view_from_summary(
                    current_summary, latest_corpus, audience, state=state, stale_reason=None
                )

    stale_summary = (
        ReviewSummary.objects.filter(job__game=game, job__audience=audience)
        .select_related("job__source_corpus")
        .order_by("-generated_at")
        .first()
    )
    if stale_summary is None:
        return _empty(audience)
    reason = current_job.state if current_job is not None else "collection_in_progress"
    return _view_from_summary(
        stale_summary, stale_summary.job.source_corpus, audience, state="stale", stale_reason=reason
    )


def get_summaries(game: Game) -> list[SummaryView]:
    return [_summary_view(game, audience) for audience in AUDIENCES]
