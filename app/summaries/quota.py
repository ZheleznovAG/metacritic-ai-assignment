"""Persistent minute/day token-quota admission check, using committed `SummaryAttempt` rows as
the ledger (no separate counter table: every reservation is already a persisted attempt).

Free Plan snapshot per `research/feasibility/ai-summary.md`: 8,000 TPM / 200,000 TPD.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Sum
from processing.clock import Clock

from summaries.models import SummaryAttempt

FREE_TPM = 8000
FREE_TPD = 200000


def _reserved_since(since: datetime) -> int:
    total = SummaryAttempt.objects.filter(started_at__gte=since).aggregate(
        total=Sum("reserved_total_tokens")
    )["total"]
    return int(total or 0)


def has_capacity(clock: Clock, estimated_reservation: int) -> bool:
    now = clock.now_utc()
    minute_used = _reserved_since(now - timedelta(minutes=1))
    day_used = _reserved_since(now - timedelta(days=1))
    return (minute_used + estimated_reservation <= FREE_TPM) and (
        day_used + estimated_reservation <= FREE_TPD
    )
