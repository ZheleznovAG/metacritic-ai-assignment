"""UI-OPT-02: readable saved observations; no work ownership or provider access."""

from datetime import datetime

from django import template
from django.utils import timezone
from django.utils.dateparse import parse_datetime

register = template.Library()


@register.filter
def relative_time(value: datetime | str | None) -> str:
    try:
        observed = parse_datetime(value) if isinstance(value, str) else value
    except ValueError:
        observed = None
    if observed is None or timezone.is_naive(observed):
        return "Not recorded"
    seconds = (timezone.now() - observed).total_seconds()
    if seconds < -5:
        return "In the future"
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


@register.filter
def process_label(value: str) -> str:
    return {
        "busy": "Working",
        "idle": "Waiting",
        "stale": "Stale",
        "stopped": "Stopped",
        "unknown": "Unknown",
    }.get(value, value)
