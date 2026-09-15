"""Bounded HTTP adapter: bounded total response size/time per attempt, bounded retry with
backoff on transient failures (`HRD-01`)."""

import hashlib
import time
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
# httpx's own `timeout` only bounds the wait for each individual connect/read/write/pool
# operation, not the total duration of a slow but steadily-trickling response, and it never
# bounds response *size* at all — a response can be read to completion in memory regardless of
# how large it is. RESPONSE_DEADLINE_SECONDS/MAX_RESPONSE_BYTES close both gaps for the decoded
# body httpx hands us. They do not, by themselves, bound a compressed response's *decoded* size
# per decode() call — a compression bomb could still spike memory inside httpx's own decoder
# before our check runs on the next iteration. `Accept-Encoding: identity` below removes that
# gap in practice by asking the server not to compress at all, rather than trying to out-guess
# arbitrary compression ratios; a source that ignored it anyway is not defended against here.
REQUEST_TIMEOUT_SECONDS = 15.0
RESPONSE_DEADLINE_SECONDS = 30.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_STREAM_CHUNK_SIZE = 65536
# A short, bounded, in-call retry is only for failures likely to be transient at the transport
# level (connection resets, generic upstream 5xx). 403 is not retried (immediate, not transient);
# 429 is not retried in-call either — the outer hourly/daily cycle already retries failed work
# on its own schedule, matching how every other retry in this app already works, rather than
# spinning against a live rate limit inside one call.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (0.5, 1.0)
if len(RETRY_BACKOFF_SECONDS) < MAX_ATTEMPTS - 1:
    raise ValueError("RETRY_BACKOFF_SECONDS needs one value per possible retry")
_RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})


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


def review_page_url(audience: str, game_slug: str, platform_slug: str, cursor: str | None) -> str:
    return cursor if cursor is not None else _initial_review_url(audience, game_slug, platform_slug)


class MetacriticGateway:
    def __init__(
        self, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._client = client or httpx.Client(
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        )
        self._owns_client = client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(
        self, url: str, kind: str, validate: Callable[[str], None] = _validate_url
    ) -> tuple[str | None, FetchEvidence]:
        validate(url)
        for attempt in range(MAX_ATTEMPTS):
            body, evidence, retryable = self._attempt(url, kind)
            if body is not None or not retryable or attempt + 1 >= MAX_ATTEMPTS:
                return body, evidence
            self._sleep(RETRY_BACKOFF_SECONDS[attempt])
        raise AssertionError("unreachable: the loop above always returns")

    def _attempt(self, url: str, kind: str) -> tuple[str | None, FetchEvidence, bool]:
        """Returns `(body, evidence, retryable)`. `retryable` is only ever `True` alongside
        `body is None`, for a transient failure worth a bounded in-call retry."""
        started_at = datetime.now(tz=UTC)
        deadline = time.monotonic() + RESPONSE_DEADLINE_SECONDS
        try:
            with self._client.stream("GET", url) as response:
                status = response.status_code
                # Accumulated manually rather than via `response.content`/`.text`: after
                # `iter_bytes()` is exhausted by hand (as opposed to calling `response.read()`),
                # httpx has not internally cached the body, and both properties raise
                # `ResponseNotRead` — a `RuntimeError`, not an `httpx.HTTPError`, so it would
                # crash every call instead of being classified as a failure.
                body = bytearray()
                too_large = False
                timed_out = False
                for chunk in response.iter_bytes(chunk_size=_STREAM_CHUNK_SIZE):
                    body += chunk
                    if len(body) > MAX_RESPONSE_BYTES:
                        too_large = True
                        break
                    if time.monotonic() > deadline:
                        timed_out = True
                        break
                if too_large:
                    return (
                        None,
                        self._evidence(kind, url, started_at, status, None, "response_too_large"),
                        False,
                    )
                if timed_out:
                    return (
                        None,
                        self._evidence(
                            kind, url, started_at, status, None, "response_deadline_exceeded"
                        ),
                        False,
                    )
                raw = bytes(body)
                sha256 = hashlib.sha256(raw).hexdigest()
                if status != httpx.codes.OK:
                    return (
                        None,
                        self._evidence(kind, url, started_at, status, sha256, f"http_{status}"),
                        status in _RETRYABLE_STATUS_CODES,
                    )
                text = raw.decode(response.encoding or "utf-8", errors="replace")
                return (
                    text,
                    self._evidence(kind, url, started_at, status, sha256, None),
                    False,
                )
        except httpx.TransportError as error:
            # Genuinely transport-level (connection reset, timeout, protocol error): worth a
            # bounded in-call retry.
            return (
                None,
                self._evidence(kind, url, started_at, None, None, type(error).__name__),
                True,
            )
        except httpx.HTTPError as error:
            # A non-transport httpx error (e.g. malformed content-encoding, too many redirects)
            # would fail identically on retry — not retryable.
            return (
                None,
                self._evidence(kind, url, started_at, None, None, type(error).__name__),
                False,
            )

    def _evidence(
        self,
        kind: str,
        url: str,
        started_at: datetime,
        http_status: int | None,
        response_sha256: str | None,
        error_code: str | None,
    ) -> FetchEvidence:
        return FetchEvidence(
            kind=kind,
            url=url,
            started_at=started_at,
            completed_at=datetime.now(tz=UTC),
            http_status=http_status,
            response_sha256=response_sha256,
            parser_contract_version=PARSER_CONTRACT_VERSION,
            outcome="succeeded" if error_code is None else "failed",
            error_code=error_code,
        )

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
        url = review_page_url(audience, game_slug, platform_slug, cursor)
        body, evidence = self._get(url, kind="review_page", validate=_validate_review_url)
        if body is None:
            return None, evidence
        try:
            return parse_review_page(body, audience, game_slug, platform_slug), evidence
        except MetacriticParseError as error:
            return None, replace(evidence, outcome="invalid", error_code=type(error).__name__)
