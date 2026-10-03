"""Advance one game's let's play by one external step per call (search, listen or conclude).

Runs in the worker's idle time, after review pages and summaries. Each step: claim a due job under
a lease, ask the budget for the provider units, release every database lock for the one external
call, then record the result with a fencing check. A step that cannot run now (no budget, provider
refused) moves `available_at`; repeated errors end in `failed` with the reason the card shows.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Protocol

from catalog.models import Game
from core.clock import Clock
from django.db import transaction
from django.db.models import F, Max, Q
from summaries.groq_adapter import GroqApiError

from letsplays import budget, conclusion, selection
from letsplays.groq import ChatResult
from letsplays.models import LetsPlay, LetsPlayConclusion, LetsPlayTranscript
from letsplays.youtube import (
    NETWORK_CODES,
    Found,
    Heard,
    VideoFacts,
    YouTubeError,
    search_units,
)

LEASE = timedelta(minutes=10)
REFRESH_AFTER = timedelta(days=30)
MAX_ATTEMPTS = 5
BACKOFF = (timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=12))
WORKING = ("searching", "listening", "concluding")


class Providers(Protocol):
    """The external calls, so tests can replace YouTube and Groq with fakes."""

    def search(self, title: str) -> list[Found]: ...

    def facts(self, video_id: str) -> VideoFacts: ...

    def captions(self, video_id: str, language: str | None, seconds: int) -> Heard | None: ...

    def whisper(self, audio_url: str) -> tuple[Heard, dict[str, str]]: ...

    def chat(self, payload: dict[str, object]) -> ChatResult: ...


def _next_game() -> Game | None:
    """Games with a Metascore first (likelier to have let's plays), newest releases first."""
    return (
        Game.objects.filter(letsplay__isnull=True)
        .annotate(best=Max("platforms__metascore"))
        .order_by(F("best").desc(nulls_last=True), F("release_date").desc(nulls_last=True), "-id")
        .first()
    )


def claim(clock: Clock) -> LetsPlay | None:
    now = clock.now_utc()
    with transaction.atomic():
        due = (
            LetsPlay.objects.select_for_update(skip_locked=True)
            .filter(
                Q(state__in=WORKING, available_at__lte=now)
                | Q(state__in=WORKING, available_at__isnull=True)
                | Q(state__in=("done", "not_found", "failed"), refresh_at__lte=now)
            )
            .order_by(F("available_at").asc(nulls_first=True), "id")
            .first()
        )
        if due is None:
            game = _next_game()
            if game is None:
                return None
            due = LetsPlay.objects.create(game=game, policy_version=selection.POLICY_VERSION)
            due = LetsPlay.objects.select_for_update().get(pk=due.pk)
        if due.state not in WORKING:
            _restart(due)
        due.available_at = now + LEASE  # the lease: nobody else claims it meanwhile
        due.save(update_fields=["state", "available_at", "attempt_count", "last_error"])
        return due


def _restart(job: LetsPlay) -> None:
    job.state = "searching"
    job.attempt_count = 0
    job.last_error = None


def _later(job: LetsPlay, now: datetime, until: datetime, reason: str) -> str:
    job.available_at = until
    job.last_error = reason
    job.save(update_fields=["available_at", "last_error"])
    return f"{job.state}: waiting ({reason})"


def _error(job: LetsPlay, now: datetime, code: str) -> str:
    job.attempt_count += 1
    job.last_error = code
    if job.attempt_count >= MAX_ATTEMPTS:
        job.state = "failed"
        job.available_at = None
        job.refresh_at = now + REFRESH_AFTER
    else:
        job.available_at = now + BACKOFF[min(job.attempt_count - 1, len(BACKOFF) - 1)]
    job.save(update_fields=["state", "attempt_count", "last_error", "available_at", "refresh_at"])
    return f"{job.state}: {code}"


def _owned(job: LetsPlay, lease_until: datetime | None) -> LetsPlay | None:
    current = LetsPlay.objects.select_for_update().get(pk=job.pk)
    return current if current.available_at == lease_until and current.state == job.state else None


def advance(clock: Clock, providers: Providers) -> str | None:
    """Run one step for one due game; None when there is nothing to do."""
    job = claim(clock)
    if job is None:
        return None
    if job.state == "searching":
        return _search(clock, providers, job)
    if job.state == "listening":
        return _listen(clock, providers, job)
    return _conclude(clock, providers, job)


def _search(clock: Clock, providers: Providers, job: LetsPlay) -> str:
    lease = job.available_at
    now = clock.now_utc()
    units = search_units(50)
    with transaction.atomic():
        call = budget.admit("youtube_api", units, now, letsplay_id=job.pk)
        if call is None:
            until = budget.blocked_until("youtube_api", units, now) or now + LEASE
            return _later(job, now, until, "youtube_quota")
    title = job.game.title
    try:
        found = providers.search(title)
    except YouTubeError as error:
        now = clock.now_utc()
        with transaction.atomic():
            refused = error.code == "youtube_quota_exceeded"
            budget.finish(call, now, "refused" if refused else "failed", error_code=error.code)
            current = _owned(job, lease)
            if current is None:
                return "searching: lease lost"
            if refused:
                return _later(current, now, now + timedelta(hours=24), error.code)
            return _error(current, now, error.code)
    now = clock.now_utc()
    candidates = [
        selection.Candidate(
            video_id=item.video_id,
            title=item.title,
            channel=item.channel,
            views=item.views,
            seconds=item.seconds,
            language=item.language,
            live=item.live,
        )
        for item in found
    ]
    shortlist = selection.shortlist(candidates)[: selection.MAX_LISTENS]
    with transaction.atomic():
        budget.finish(call, now, "ok", actual_units=search_units(len(found)))
        current = _owned(job, lease)
        if current is None:
            return "searching: lease lost"
        current.searched_at = now
        current.policy_version = selection.POLICY_VERSION
        current.shortlist = [asdict(item) for item in shortlist]
        current.checks = []
        current.video_id = current.video_title = current.channel = None
        current.views = current.seconds = None
        current.attempt_count = 0
        current.last_error = None
        if shortlist:
            current.state, current.available_at = "listening", now
        else:
            current.state, current.available_at = "not_found", None
            current.refresh_at = now + REFRESH_AFTER
        current.save()
        return f"{current.state}: {len(found)} found, {len(shortlist)} to hear"


def _hear(
    clock: Clock, providers: Providers, job: LetsPlay, video_id: str
) -> tuple[Heard | None, str, str | None]:
    """Captions when the budget allows, otherwise the Whisper fragment of the original audio.

    Returns (speech or None, source, a reason to wait instead).
    """
    facts = providers.facts(video_id)
    now = clock.now_utc()
    with transaction.atomic():
        call = budget.admit("captions", 1, now, letsplay_id=job.pk, video_id=video_id)
    if call is not None:
        try:
            heard = providers.captions(video_id, facts.language, facts.seconds)
        except YouTubeError as error:
            blocked = error.code == "captions_blocked"
            with transaction.atomic():
                outcome = "refused" if blocked else "failed"
                budget.finish(call, clock.now_utc(), outcome, error_code=error.code)
            heard = None
        else:
            with transaction.atomic():
                budget.finish(call, clock.now_utc(), "ok" if heard else "none")
            if heard is not None:
                # Captions in the original language; their language code is the spoken one.
                return heard, "captions", None
    if not facts.audio_url:
        return None, "whisper", None
    now = clock.now_utc()
    with transaction.atomic():
        audio = budget.admit("audio", 1, now, letsplay_id=job.pk, video_id=video_id)
        whisper = (
            budget.admit("whisper", 320, now, letsplay_id=job.pk, video_id=video_id)
            if audio
            else None
        )
        if audio is None or whisper is None:
            if audio is not None:
                budget.finish(audio, now, "skipped", error_code="whisper_budget")
            return None, "whisper", "whisper_budget"
    try:
        heard, headers = providers.whisper(facts.audio_url)
    except YouTubeError as error:
        with transaction.atomic():
            now = clock.now_utc()
            budget.finish(audio, now, "failed", error_code=error.code)
            budget.finish(whisper, now, "skipped", error_code=error.code)
        if error.code in NETWORK_CODES:
            raise  # nothing learned about the video: retry the step, keep the listen
        return None, "whisper", None
    except GroqApiError as error:
        with transaction.atomic():
            now = clock.now_utc()
            budget.finish(audio, now, "ok")
            refused = error.status == 429
            budget.finish(
                whisper,
                now,
                "refused" if refused else "failed",
                error_code="rate_limited" if refused else "transport_error",
                headers=error.rate_limit_headers,
            )
        return None, "whisper", "whisper_refused" if refused else "whisper_error"
    with transaction.atomic():
        now = clock.now_utc()
        budget.finish(audio, now, "ok")
        budget.finish(whisper, now, "ok", actual_units=round(heard.seconds or 0), headers=headers)
    return heard, "whisper", None


def _listen(clock: Clock, providers: Providers, job: LetsPlay) -> str:
    lease = job.available_at
    position = len(job.checks)
    target = job.shortlist[position] if position < len(job.shortlist) else None
    if target is None:
        with transaction.atomic():
            current = _owned(job, lease)
            if current is None:
                return "listening: lease lost"
            return _not_found(current, clock.now_utc())
    candidate = selection.Candidate(**target)
    unavailable: str | None = None
    try:
        heard, source, wait = _hear(clock, providers, job, candidate.video_id)
    except YouTubeError as error:
        if error.code in NETWORK_CODES:
            with transaction.atomic():
                current = _owned(job, lease)
                if current is None:
                    return "listening: lease lost"
                return _error(current, clock.now_utc(), error.code)
        heard, source, wait = None, "whisper", None
        unavailable = error.code
    now = clock.now_utc()
    with transaction.atomic():
        current = _owned(job, lease)
        if current is None:
            return "listening: lease lost"
        if wait is not None:
            if wait == "whisper_error":
                return _error(current, now, wait)
            until = budget.blocked_until("whisper", 320, now) or now + timedelta(minutes=10)
            return _later(current, now, until, wait)
        speech = selection.Speech(heard.language, heard.text, heard.seconds) if heard else None
        choice = selection.choose(current.game.title, [candidate], lambda item: speech)
        check = choice.checks[0]
        current.checks = [
            *current.checks,
            {
                "video_id": check.video_id,
                "decision": check.decision,
                "words_per_minute": check.words_per_minute,
                "source": source if heard else None,
                "reason": unavailable,
            },
        ]
        if choice.video_id is None or heard is None:
            current.save(update_fields=["checks"])
            if len(current.checks) >= min(selection.MAX_LISTENS, len(current.shortlist)):
                return _not_found(current, now)
            current.available_at = now
            current.save(update_fields=["available_at"])
            return f"listening: {candidate.video_id} {check.decision}"
        LetsPlayTranscript.objects.create(
            letsplay=current,
            video_id=candidate.video_id,
            source=source,
            language=heard.language,
            seconds_covered=heard.seconds,
            text=heard.text,
            text_sha256=hashlib.sha256(heard.text.encode("utf-8")).hexdigest(),
            created_at=now,
        )
        current.video_id = candidate.video_id
        current.video_title = candidate.title
        current.channel = candidate.channel
        current.views = candidate.views
        current.seconds = candidate.seconds
        current.state = "concluding"
        current.available_at = now
        current.attempt_count = 0
        current.last_error = None
        current.save()
        return f"concluding: chose {candidate.video_id}"


def _not_found(job: LetsPlay, now: datetime) -> str:
    job.state = "not_found"
    job.available_at = None
    job.refresh_at = now + REFRESH_AFTER
    job.save(update_fields=["state", "available_at", "refresh_at"])
    return "not_found"


def _conclude(clock: Clock, providers: Providers, job: LetsPlay) -> str:
    lease = job.available_at
    transcript = job.transcripts.filter(video_id=job.video_id).order_by("-id").first()
    now = clock.now_utc()
    if transcript is None:
        with transaction.atomic():
            current = _owned(job, lease)
            return _error(current, now, "transcript_missing") if current else "lease lost"
    fingerprint = conclusion.contour_fingerprint()
    if transcript.conclusions.filter(contour_fingerprint=fingerprint).exists():
        with transaction.atomic():
            current = _owned(job, lease)
            if current is None:
                return "concluding: lease lost"
            return _done(current, now)
    case_id = f"letsplay-{job.pk}"
    try:
        prepared = conclusion.prepare(case_id, job.game.title, transcript.text)
    except conclusion.BudgetError:
        with transaction.atomic():
            current = _owned(job, lease)
            return _error(current, now, "transcript_too_long") if current else "lease lost"
    with transaction.atomic():
        call = budget.admit("chat", prepared.reserved_tokens, now, letsplay_id=job.pk)
        if call is None:
            until = budget.blocked_until("chat", prepared.reserved_tokens, now) or now + LEASE
            return _later(job, now, until, "chat_budget")
    try:
        result = providers.chat(prepared.payload)
    except GroqApiError as error:
        now = clock.now_utc()
        with transaction.atomic():
            refused = error.status == 429
            budget.finish(
                call,
                now,
                "refused" if refused else "failed",
                error_code="rate_limited" if refused else "transport_error",
                headers=error.rate_limit_headers,
            )
            current = _owned(job, lease)
            if current is None:
                return "concluding: lease lost"
            if refused:
                return _later(
                    current, now, now + timedelta(seconds=error.retry_after or 60), "chat_refused"
                )
            return _error(current, now, "chat_error")
    now = clock.now_utc()
    errors = conclusion.validate_output(result.output, case_id, set(prepared.segments))
    with transaction.atomic():
        budget.finish(call, now, "ok", actual_units=result.total_tokens, headers=result.headers)
        current = _owned(job, lease)
        if current is None:
            return "concluding: lease lost"
        if errors:
            return _error(current, now, "malformed_conclusion")
        output = result.output
        LetsPlayConclusion.objects.create(
            letsplay=current,
            transcript=transcript,
            contour_fingerprint=fingerprint,
            contour_versions=conclusion.contour_versions(),
            status=output["status"],
            verdict=output["verdict"],
            sponsored=output["sponsored"],
            opinions=conclusion.opinions(output, prepared.segments),
            returned_model=result.returned_model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            generated_at=now,
        )
        return _done(current, now)


def _done(job: LetsPlay, now: datetime) -> str:
    job.state = "done"
    job.available_at = None
    job.attempt_count = 0
    job.last_error = None
    job.refresh_at = now + REFRESH_AFTER
    job.save(update_fields=["state", "available_at", "attempt_count", "last_error", "refresh_at"])
    return f"done: {job.video_id}"
