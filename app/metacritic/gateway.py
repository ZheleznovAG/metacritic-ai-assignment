"""Bounded single-request HTTP adapter; no retry/backoff policy (that is `HRD-01`)."""

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from urllib.parse import quote_plus, urlencode

import httpx

from metacritic.dto import BrowsePage, FetchEvidence, GameDTO, GameIdentityDTO, ReviewPageDTO
from metacritic.errors import MetacriticFetchError, MetacriticParseError
from metacritic.parser import (
    PARSER_CONTRACT_VERSION,
    parse_browse_page,
    parse_game_detail,
    parse_new_releases,
    parse_platform_userscore,
    parse_review_page,
)

ALLOWED_HOST = "www.metacritic.com"
NEW_RELEASES_URL = "https://www.metacritic.com/game/"
BROWSE_LISTING_URL = "https://www.metacritic.com/browse/game/all/all/all-time/new/"

# Confirmed live during IMP-04 (see docs/requirements/imp_04_review.md): the initial backend
# review-list URL for a route, captured from the web review page's own embedded SSR link. Every
# subsequent page is reached only via the previous response's `links.next.href`, never by
# reconstructing this template again — this pins the one-time "confirmed backend link" `docs/
# design.md` asks for without an extra web-page fetch per collection job.
REVIEW_BACKEND_HOST = "backend.metacritic.com"
_REVIEW_PAGE_LIMIT = {"critic": 10, "user": 50}
_REVIEW_PAGE_SORT = {"critic": "score", "user": "date"}


class GatewayProtocol(Protocol):
    """What `catalog.ingest`/`processing` need; lets tests pass a fake instead of a real
    `MetacriticGateway`."""

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]: ...

    def fetch_platform_userscore(self, url: str) -> tuple[Decimal | None, FetchEvidence]: ...

    def list_new_releases(self) -> tuple[list[GameIdentityDTO] | None, FetchEvidence]: ...

    def iter_browse(self, page: int) -> tuple[BrowsePage | None, FetchEvidence]: ...

    def fetch_review_page(
        self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
    ) -> tuple[ReviewPageDTO | None, FetchEvidence]: ...


class ReviewGatewayProtocol(Protocol):
    """What `reviews.collector` needs; narrower than `GatewayProtocol` so its fakes don't have to
    stub unrelated game/listing fetch methods."""

    def fetch_review_page(
        self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
    ) -> tuple[ReviewPageDTO | None, FetchEvidence]: ...


USER_AGENT = (
    "metacritic-ai-assignment-ingest/1.0 (+https://github.com/ZheleznovAG/metacritic-ai-assignment)"
)
REQUEST_TIMEOUT_SECONDS = 15.0


def _validate_url(url: str) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host != ALLOWED_HOST:
        raise MetacriticFetchError(f"URL is not on the allowlisted host: {url}")
    if not (parsed.path.startswith("/game/") or parsed.path.startswith("/browse/game/")):
        raise MetacriticFetchError(f"URL is not a recognised game/listing route: {url}")


def _validate_review_url(url: str) -> None:
    parsed = httpx.URL(url)
    if parsed.scheme != "https" or parsed.host != REVIEW_BACKEND_HOST:
        raise MetacriticFetchError(f"URL is not on the allowlisted review backend host: {url}")
    if not parsed.path.startswith("/reviews/metacritic/"):
        raise MetacriticFetchError(f"URL is not a recognised review route: {url}")


def _initial_review_url(audience: str, game_slug: str, platform_slug: str) -> str:
    query = urlencode(
        {
            "offset": 0,
            "limit": _REVIEW_PAGE_LIMIT[audience],
            "filterBySentiment": "all",
            "sort": _REVIEW_PAGE_SORT[audience],
            "componentName": f"{audience}-reviews",
            "componentDisplayName": f"{audience} Reviews",
            "componentType": "ReviewList",
        },
        quote_via=quote_plus,
    )
    return (
        f"https://{REVIEW_BACKEND_HOST}/reviews/metacritic/{audience}/games/{game_slug}"
        f"/platform/{platform_slug}/web?{query}"
    )


class MetacriticGateway:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(
        self, url: str, kind: str, validate: Callable[[str], None] = _validate_url
    ) -> tuple[str | None, FetchEvidence]:
        validate(url)
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

    def list_new_releases(self) -> tuple[list[GameIdentityDTO] | None, FetchEvidence]:
        body, evidence = self._get(NEW_RELEASES_URL, kind="new_releases")
        if body is None:
            return None, evidence
        try:
            return parse_new_releases(body, NEW_RELEASES_URL), evidence
        except MetacriticParseError as error:
            return None, replace(evidence, outcome="invalid", error_code=type(error).__name__)

    def iter_browse(self, page: int) -> tuple[BrowsePage | None, FetchEvidence]:
        url = f"{BROWSE_LISTING_URL}?page={page}"
        body, evidence = self._get(url, kind="browse_page")
        if body is None:
            return None, evidence
        try:
            return parse_browse_page(body, url), evidence
        except MetacriticParseError as error:
            return None, replace(evidence, outcome="invalid", error_code=type(error).__name__)

    def fetch_review_page(
        self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
    ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
        url = (
            cursor
            if cursor is not None
            else _initial_review_url(audience, game_slug, platform_slug)
        )
        body, evidence = self._get(url, kind="review_page", validate=_validate_review_url)
        if body is None:
            return None, evidence
        try:
            return parse_review_page(body, audience, game_slug, platform_slug), evidence
        except MetacriticParseError as error:
            return None, replace(evidence, outcome="invalid", error_code=type(error).__name__)
