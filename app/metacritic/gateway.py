"""Bounded single-request HTTP adapter; no retry/backoff policy (that is `HRD-01`)."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx

from metacritic.dto import FetchEvidence, GameDTO
from metacritic.errors import MetacriticFetchError, MetacriticParseError
from metacritic.parser import PARSER_CONTRACT_VERSION, parse_game_detail, parse_platform_userscore

ALLOWED_HOST = "www.metacritic.com"


class GatewayProtocol(Protocol):
    """What `catalog.ingest` needs; lets tests pass a fake instead of a real `MetacriticGateway`."""

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]: ...

    def fetch_platform_userscore(self, url: str) -> tuple[Decimal | None, FetchEvidence]: ...


USER_AGENT = (
    "metacritic-ai-assignment-ingest/1.0 (+https://github.com/ZheleznovAG/metacritic-ai-assignment)"
)
REQUEST_TIMEOUT_SECONDS = 15.0


def _validate_url(url: str) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host != ALLOWED_HOST:
        raise MetacriticFetchError(f"URL is not on the allowlisted host: {url}")
    if not parsed.path.startswith("/game/"):
        raise MetacriticFetchError(f"URL is not a recognised game route: {url}")


class MetacriticGateway:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(self, url: str, kind: str) -> tuple[str | None, FetchEvidence]:
        _validate_url(url)
        started_at = datetime.now(tz=UTC)
        try:
            response = self._client.get(url)
        except httpx.HTTPError as error:
            completed_at = datetime.now(tz=UTC)
            return None, FetchEvidence(
                kind=kind,
                url=url,
                started_at=started_at,
                completed_at=completed_at,
                http_status=None,
                response_sha256=None,
                parser_contract_version=PARSER_CONTRACT_VERSION,
                outcome="failed",
                error_code=type(error).__name__,
            )
        completed_at = datetime.now(tz=UTC)
        sha256 = hashlib.sha256(response.content).hexdigest()
        if response.status_code != httpx.codes.OK:
            return None, FetchEvidence(
                kind=kind,
                url=url,
                started_at=started_at,
                completed_at=completed_at,
                http_status=response.status_code,
                response_sha256=sha256,
                parser_contract_version=PARSER_CONTRACT_VERSION,
                outcome="failed",
                error_code=f"http_{response.status_code}",
            )
        evidence = FetchEvidence(
            kind=kind,
            url=url,
            started_at=started_at,
            completed_at=completed_at,
            http_status=response.status_code,
            response_sha256=sha256,
            parser_contract_version=PARSER_CONTRACT_VERSION,
            outcome="succeeded",
            error_code=None,
        )
        return response.text, evidence

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        body, evidence = self._get(url, kind="game_detail")
        if body is None:
            return None, evidence
        try:
            return parse_game_detail(body, url), evidence
        except MetacriticParseError as error:
            return None, replace(evidence, outcome="invalid", error_code=type(error).__name__)

    def fetch_platform_userscore(self, url: str) -> tuple[Decimal | None, FetchEvidence]:
        body, evidence = self._get(url, kind="platform_userscore")
        if body is None:
            return None, evidence
        try:
            return parse_platform_userscore(body, url), evidence
        except MetacriticParseError as error:
            return None, replace(evidence, outcome="invalid", error_code=type(error).__name__)
