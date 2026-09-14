"""R09: atomic provider admission using a transaction advisory lock and durable attempts."""

import math
import re
from datetime import datetime, timedelta

from django.db import connection
from processing.clock import Clock

from summaries.models import SummaryAttempt

FREE_TPM = 8000
FREE_TPD = 200000
FREE_RPM = 30
FREE_RPD = 1000
QUOTA_LOCK_ID = 7065700301  # One Groq credential/account contour in this application database.


def lock_admission() -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("quota admission requires a transaction")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [QUOTA_LOCK_ID])


def budget_halted(contour_fingerprint: str) -> bool:
    return SummaryAttempt.objects.filter(
        error_code="usage_exceeds_budget", job__contour_fingerprint=contour_fingerprint
    ).exists()


def _seconds(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        value = float(raw)
    except ValueError:
        parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", raw)
        if not parts or "".join(number + unit for number, unit in parts) != raw:
            return None
        scales = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}
        value = sum(float(number) * scales[unit] for number, unit in parts)
    return min(value, 86400) if math.isfinite(value) and value >= 0 else None


def _integer(raw: object) -> int | None:
    try:
        value = int(str(raw))
    except (ValueError, TypeError):
        return None
    return value if value >= 0 else None


def _blocks(now: datetime, amount: int) -> list[datetime]:
    rows = list(
        SummaryAttempt.objects.filter(started_at__gt=now - timedelta(days=1)).order_by(
            "started_at", "id"
        )
    )
    blocks: list[datetime] = []
    for window, token_limit, request_limit in (
        (timedelta(minutes=1), FREE_TPM, FREE_RPM),
        (timedelta(days=1), FREE_TPD, FREE_RPD),
    ):
        recent = [row for row in rows if row.started_at > now - window]
        for costs, limit, incoming in (
            ([row.reserved_total_tokens for row in recent], token_limit, amount),
            ([1 for _ in recent], request_limit, 1),
        ):
            excess = sum(costs) + incoming - limit
            if excess > 0:
                for row, cost in zip(recent, costs, strict=True):
                    excess -= cost
                    if excess <= 0:
                        blocks.append(row.started_at + window)
                        break
                else:
                    blocks.append(now + window)
    if not rows:
        return blocks
    latest = rows[-1]
    headers = latest.rate_limit_headers
    observed = latest.completed_at if latest.outcome != "abandoned" else None
    reference = observed or latest.started_at
    # An in-flight request has no reliable remaining budget yet. Recovery closes it as abandoned.
    if latest.outcome is None and now < latest.started_at + timedelta(minutes=5):
        blocks.append(now + timedelta(minutes=1))
    for unit, required in (("tokens", amount), ("requests", 1)):
        remaining = _integer(headers.get(f"x-ratelimit-remaining-{unit}"))
        reset = _seconds(headers.get(f"x-ratelimit-reset-{unit}"))
        if remaining is None or reset is None:
            if now < reference + timedelta(minutes=1):
                blocks.append(reference + timedelta(minutes=1))
        elif remaining < required and now < reference + timedelta(seconds=reset):
            blocks.append(reference + timedelta(seconds=reset))
    if latest.error_code == "rate_limited":
        until = reference + timedelta(seconds=_seconds(headers.get("retry-after")) or 60)
        if until > now:
            blocks.append(until)
    return blocks


def has_capacity(clock: Clock, estimated_reservation: int) -> bool:
    return not _blocks(clock.now_utc(), estimated_reservation)


def next_available_at(clock: Clock, estimated_reservation: int) -> datetime:
    now = clock.now_utc()
    return max(_blocks(now, estimated_reservation), default=now + timedelta(minutes=1))
