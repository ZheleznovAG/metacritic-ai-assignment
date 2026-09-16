"""Telemetry at the real HTTP boundary, without giving the adapter an ORM dependency."""

from collections.abc import Callable

from metacritic.dto import FetchEvidence
from metacritic.gateway import (
    MAX_ATTEMPTS,
    RESPONSE_DEADLINE_SECONDS,
    RETRY_BACKOFF_SECONDS,
    MetacriticGateway,
    _validate_url,
)

from processing.heartbeat import report_progress


class ObservedGateway(MetacriticGateway):
    def _get(
        self, url: str, kind: str, validate: Callable[[str], None] = _validate_url
    ) -> tuple[str | None, FetchEvidence]:
        report_progress(
            "source_request",
            deadline_seconds=MAX_ATTEMPTS * RESPONSE_DEADLINE_SECONDS + sum(RETRY_BACKOFF_SECONDS),
        )
        try:
            return super()._get(url, kind, validate)
        finally:
            report_progress("saving")
