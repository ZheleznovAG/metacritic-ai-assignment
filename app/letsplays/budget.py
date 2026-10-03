"""Provider budgets for let's plays, enforced in provider units from the `ProviderCall` ledger.

Frozen in `evals/letsplays/metric.md` (YTP-02); the YouTube search cost follows the evaluated
two-query method (`evals/letsplays/selection_results.md`). Admission runs under one advisory lock
so two workers cannot both take the last unit. A provider refusal (HTTP 429, a blocked address)
blocks that kind until its stated retry time even when our own count says otherwise: Groq's audio
accounting did not match ours in YTP-02.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import connection
from django.db.models import Sum

from letsplays.models import ProviderCall

ADMISSION_LOCK_ID = 7065700411


@dataclass(frozen=True, slots=True)
class Window:
    span: timedelta
    calls: int | None = None
    units: int | None = None


LIMITS: dict[str, tuple[Window, ...]] = {
    # YouTube Data API: 10 000 units per day from Google; the service keeps 1 000 in reserve.
    "youtube_api": (Window(timedelta(days=1), units=9000),),
    # Captions are unofficial and the service host was blocked after ~25 quick reads.
    "captions": (Window(timedelta(minutes=2), calls=1), Window(timedelta(days=1), calls=30)),
    # Audio downloads carry no published limit; they follow the Whisper calls they feed.
    "audio": (Window(timedelta(hours=1), calls=18), Window(timedelta(days=1), calls=80)),
    # Groq Whisper free tier: 20/min, 2 000/day, 7 200 audio s/hour, 28 800/day.
    "whisper": (
        Window(timedelta(minutes=1), calls=20),
        Window(timedelta(hours=1), calls=18, units=5760),
        Window(timedelta(days=1), calls=80, units=25600),
    ),
    # Groq openai/gpt-oss-120b free tier: 8 000 tokens/min, 200 000/day; 25 conclusions a day.
    "chat": (
        Window(timedelta(minutes=1), units=8000),
        Window(timedelta(days=1), calls=25, units=200000),
    ),
}
REFUSAL_PAUSE = {
    "captions": timedelta(hours=24),
    "youtube_api": timedelta(hours=24),
}
DEFAULT_RETRY = timedelta(minutes=10)


def lock() -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("let's-play admission requires a transaction")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ADMISSION_LOCK_ID])


def blocked_until(kind: str, units: int, now: datetime) -> datetime | None:
    """None when a call of `units` may start now, otherwise when to try again."""
    blocks: list[datetime] = []
    for window in LIMITS[kind]:
        recent = ProviderCall.objects.filter(kind=kind, started_at__gt=now - window.span)
        over_calls = window.calls is not None and recent.count() + 1 > window.calls
        used = recent.aggregate(total=Sum("units"))["total"] or 0
        over_units = window.units is not None and used + units > window.units
        if over_calls or over_units:
            oldest = recent.order_by("started_at").values_list("started_at", flat=True).first()
            blocks.append((oldest or now) + window.span)
    refusal = (
        ProviderCall.objects.filter(kind=kind, outcome="refused", completed_at__isnull=False)
        .order_by("-completed_at")
        .first()
    )
    if refusal is not None and refusal.completed_at is not None:
        retry = refusal.headers.get("retry-after")
        try:
            pause = timedelta(seconds=float(retry)) if retry else None
        except ValueError:
            pause = None
        until = refusal.completed_at + (pause or REFUSAL_PAUSE.get(kind, DEFAULT_RETRY))
        if until > now:
            blocks.append(until)
    return max(blocks) if blocks else None


def admit(
    kind: str, units: int, now: datetime, *, letsplay_id: int | None, video_id: str | None = None
) -> ProviderCall | None:
    """Record the call before it is made, or return None when the budget says not yet."""
    lock()
    if blocked_until(kind, units, now) is not None:
        return None
    return ProviderCall.objects.create(
        kind=kind, letsplay_id=letsplay_id, video_id=video_id, units=units, started_at=now
    )


def finish(
    call: ProviderCall,
    now: datetime,
    outcome: str,
    *,
    actual_units: int | None = None,
    error_code: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    call.completed_at = now
    call.outcome = outcome
    call.actual_units = actual_units
    call.error_code = error_code
    call.headers = headers or {}
    call.save(update_fields=["completed_at", "outcome", "actual_units", "error_code", "headers"])
