"""Read-only let's-play view for the public card (YTP-03, AC-YT-05).

Every state says what is known and why something is missing; a conclusion is shown only when it
was validated against the transcript of the linked video. The main card never depends on it.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from catalog.models import Game
from letsplays.models import LetsPlay, LetsPlayConclusion

WAITING_REASONS = {
    "youtube_quota": "The daily YouTube search budget is used up; the search continues tomorrow.",
    "youtube_quota_exceeded": "YouTube refused more searches today; the search continues later.",
    "whisper_budget": "Speech recognition is at its hourly limit; listening continues later.",
    "video_budget": "Videos are checked slowly to stay within YouTube's limits.",
    "youtube_blocked": "YouTube is temporarily refusing this server; listening resumes later.",
    "whisper_refused": "The speech-recognition provider asked to wait; listening continues later.",
    "chat_budget": "The conclusion is waiting for model capacity.",
    "chat_refused": "The model provider asked to wait; the conclusion follows later.",
}
FAILURE_REASONS = {
    "malformed_conclusion": "The model's answer did not match the video's transcript.",
    "chat_error": "The model provider kept failing.",
    "transcript_too_long": "The transcript did not fit the conclusion budget.",
    "youtube_api_error": "YouTube search kept failing.",
    "youtube_api_unreachable": "YouTube search was unreachable.",
}


@dataclass(frozen=True, slots=True)
class OpinionView:
    point: str
    quote: str


@dataclass(frozen=True, slots=True)
class LetsPlayView:
    # pending | concluding | ok | insufficient | not_found | failed
    state: str
    video_url: str | None = None
    video_title: str | None = None
    channel: str | None = None
    views: int | None = None
    checked_on: str | None = None
    verdict: str | None = None
    sponsored: bool = False
    likes: tuple[OpinionView, ...] = ()
    dislikes: tuple[OpinionView, ...] = ()
    source: str | None = None
    minutes: int | None = None
    model_id: str | None = None
    generated_on: str | None = None
    message: str | None = None


def _day(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%d") if value else None


def get_letsplay(game: Game) -> LetsPlayView:
    job = LetsPlay.objects.filter(game=game).first()
    if job is None:
        return LetsPlayView(state="pending", message="The let's-play search has not run yet.")
    base = LetsPlayView(state="pending", checked_on=_day(job.searched_at))
    if job.video_id:
        base = replace(
            base,
            video_url=f"https://www.youtube.com/watch?v={job.video_id}",
            video_title=job.video_title,
            channel=job.channel,
            views=job.views,
        )
    latest = (
        LetsPlayConclusion.objects.filter(letsplay=job, transcript__video_id=job.video_id)
        .select_related("transcript")
        .order_by("-generated_at", "-id")
        .first()
        if job.video_id
        else None
    )
    if latest is not None and job.state in ("done", "failed"):
        transcript = latest.transcript
        heard = replace(
            base,
            source="captions" if transcript.source == "captions" else "speech recognition",
            minutes=max(1, round(transcript.seconds_covered / 60)),
            model_id=latest.returned_model or latest.contour_versions.get("requested_model"),
            generated_on=_day(latest.generated_at),
        )
        if latest.status == "insufficient":
            return replace(
                heard,
                state="insufficient",
                message="The start of this video has too little of the creator's own commentary "
                "for a conclusion.",
            )
        return replace(
            heard,
            state="ok",
            verdict=latest.verdict,
            sponsored=latest.sponsored,
            likes=_opinions(latest, "like"),
            dislikes=_opinions(latest, "dislike"),
        )
    if job.state == "not_found":
        return replace(
            base,
            state="not_found",
            message="No English let's play with the creator's own commentary was found.",
        )
    if job.state == "failed":
        reason = FAILURE_REASONS.get(job.last_error or "", "The let's-play step kept failing.")
        return replace(base, state="failed", message=reason)
    waiting = WAITING_REASONS.get(job.last_error or "")
    if job.state == "concluding":
        return replace(
            base,
            state="concluding",
            message=waiting or "The conclusion for this video is being written.",
        )
    return replace(
        base,
        state="pending",
        message=waiting or "Looking for the most popular English let's play on YouTube.",
    )


def _opinions(result: LetsPlayConclusion, polarity: str) -> tuple[OpinionView, ...]:
    return tuple(
        OpinionView(item["point"], item["quote"])
        for item in result.opinions
        if item["polarity"] == polarity
    )
