"""Pure HTML/SSR extraction for one Metacritic game-detail page (or a platform user-reviews page).

No network access happens here. Field provenance matches
`research/feasibility/metacritic-contract.md`'s field map:

- title/cover/description/trailer come from the page's JSON-LD ``VideoGame`` block.
- game identity, platform identity and per-platform Metascore come from the ``__NUXT_DATA__``
  SSR payload, which is Nuxt's positionally-indexed/dedup array format: every object/array field
  value is an index into the *same* top-level array, resolved with exactly one lookup per level
  (a resolved value that is itself a dict/list has its own fields/items resolved the same way; a
  resolved scalar is the terminal value and is never dereferenced again). The lead/current
  platform's Metascore display widget was independently observed to sometimes show a stale "TBD"
  in the raw SSR HTML while the JSON-LD and ``__NUXT_DATA__`` payload already agree on the real
  score, so the payload (not the display widget) is the source of truth for Metascore.
- developer is not in JSON-LD; it is read from the ``data-testid="hero-summary-developer"`` DOM
  fragment.
- Userscore is not in ``__NUXT_DATA__`` at all; the lead platform's Userscore is read from the
  page's own hero score widget, and every other platform's Userscore requires a separate fetch of
  its ``/user-reviews/?platform=<slug>`` page (see ``parse_platform_userscore``).
"""

import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from metacritic.dto import BrowsePage, GameDTO, GameIdentityDTO, GamePlatformDTO
from metacritic.errors import MetacriticParseError

PARSER_CONTRACT_VERSION = "1.0.0"

_USER_SCORE_TITLE = re.compile(r"^User score ([0-9]+(?:\.[0-9]+)?) out of 10$")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _safe_url(value: object) -> str | None:
    """Only http(s) URLs are trusted for storage/rendering; anything else (e.g. `javascript:`) is
    treated as absent rather than passed through to a template `href`/`src`."""
    if not isinstance(value, str) or not value:
        return None
    return value if urlsplit(value).scheme in ("http", "https") else None


def _resolve(payload: list[object], index: object) -> object:
    if not isinstance(index, int) or isinstance(index, bool) or not (0 <= index < len(payload)):
        return None
    return payload[index]


def _find_game_record(payload: list[object], expected_slug: str) -> dict[str, object]:
    # The payload can carry other "game-title"-shaped records (e.g. a "similar games" widget);
    # matching the slug this page was actually requested for avoids picking up the wrong one.
    for value in payload:
        if not isinstance(value, dict) or "platforms" not in value or "type" not in value:
            continue
        if _resolve(payload, value["type"]) != "game-title":
            continue
        if _resolve(payload, value.get("slug")) == expected_slug:
            return value
    raise MetacriticParseError(
        f"__NUXT_DATA__ payload has no game-title record matching slug {expected_slug!r}"
    )


def _slug_from_url(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]


def _extract_canonical_url(soup: BeautifulSoup) -> str | None:
    tag = _find_by_attr(soup, "link", "rel", "canonical")
    if tag is not None:
        href = tag.get("href")
        if isinstance(href, str) and href:
            return href
    meta = _find_by_attr(soup, "meta", "property", "og:url")
    if meta is not None:
        content = meta.get("content")
        if isinstance(content, str) and content:
            return content
    return None


def _require_matching_canonical(soup: BeautifulSoup, expected_url: str) -> None:
    """Guards against a silent redirect/misroute returning a different page than requested
    (e.g. a different platform's score attributed to the one that was asked for). Only used for
    game-detail/platform pages, which are canonically distinguishable per page — unlike the SEE
    ALL listing, see `_require_matching_browse_listing`."""
    canonical = _extract_canonical_url(soup)
    if canonical is None:
        raise MetacriticParseError("Page has no canonical/og:url to verify its identity")
    if canonical.rstrip("/") != expected_url.rstrip("/"):
        raise MetacriticParseError(
            f"Page canonical {canonical!r} does not match the requested {expected_url!r}"
        )


def _parse_platform(payload: list[object], record: dict[str, object]) -> GamePlatformDTO:
    source_platform_id = _resolve(payload, record.get("id"))
    name = _resolve(payload, record.get("name"))
    related = _resolve(payload, record.get("relatedGameId"))
    slug = _resolve(payload, record.get("slug"))
    identity_fields = (source_platform_id, name, slug)
    if not all(isinstance(v, (str, int)) and str(v) for v in identity_fields):
        raise MetacriticParseError("Platform record is missing id/name/slug")
    if not isinstance(related, (str, int)) or not str(related):
        # source_game_platform_id is a mandatory identity assertion (SPK-03), not an optional
        # field: an empty placeholder here would collide across platforms and corrupt identity.
        raise MetacriticParseError("Platform record is missing relatedGameId")
    critic_summary = _resolve(payload, record.get("criticScoreSummary"))
    metascore: int | None = None
    critic_path: str | None = None
    if isinstance(critic_summary, dict):
        raw_score = _resolve(payload, critic_summary.get("score"))
        if isinstance(raw_score, int) and not isinstance(raw_score, bool):
            metascore = raw_score
        raw_url = _resolve(payload, critic_summary.get("url"))
        if isinstance(raw_url, str) and raw_url:
            critic_path = raw_url
    user_path = None
    if critic_path and "critic-reviews" in critic_path:
        user_path = critic_path.replace("critic-reviews", "user-reviews")
    is_lead = bool(_resolve(payload, record.get("isLeadPlatform")))
    return GamePlatformDTO(
        source_platform_id=str(source_platform_id),
        source_game_platform_id=str(related),
        slug=str(slug),
        name=_collapse(str(name)),
        is_lead_platform=is_lead,
        metascore=metascore,
        userscore=None,
        critic_reviews_path=critic_path,
        user_reviews_path=user_path,
    )


def _extract_json_ld(soup: BeautifulSoup) -> dict[str, object]:
    tag = soup.find("script", attrs={"type": "application/ld+json"})
    if tag is None or not tag.string:
        raise MetacriticParseError("Missing JSON-LD VideoGame block")
    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError as error:
        raise MetacriticParseError("JSON-LD block is not valid JSON") from error
    if not isinstance(data, dict) or data.get("@type") != "VideoGame":
        raise MetacriticParseError("JSON-LD block is not a VideoGame record")
    return data


def _extract_nuxt_payload(soup: BeautifulSoup) -> list[object]:
    tag = soup.find("script", attrs={"id": "__NUXT_DATA__"})
    if tag is None or not tag.string:
        raise MetacriticParseError("Missing __NUXT_DATA__ payload")
    try:
        payload = json.loads(tag.string)
    except json.JSONDecodeError as error:
        raise MetacriticParseError("__NUXT_DATA__ payload is not valid JSON") from error
    if not isinstance(payload, list):
        raise MetacriticParseError("__NUXT_DATA__ payload has an unexpected shape")
    return payload


def _find_by_testid(node: BeautifulSoup | Tag, value: str) -> Tag | None:
    return _find_by_attr(node, None, "data-testid", value)


def _find_by_attr(node: BeautifulSoup | Tag, name: str | None, attr: str, value: str) -> Tag | None:
    # bs4-stubs' find() overloads are stricter than the runtime signature about `name`/`attrs`.
    result = node.find(name, attrs={attr: value})  # type: ignore[arg-type]
    return result if isinstance(result, Tag) else None


def _find_all_by_attr(node: BeautifulSoup | Tag, attr: str, value: str) -> list[Tag]:
    # Same bs4-stubs overload strictness as `_find_by_attr`, for find_all().
    results = node.find_all(attrs={attr: value})  # type: ignore[call-overload]
    return [tag for tag in results if isinstance(tag, Tag)]


def _extract_developer(soup: BeautifulSoup) -> str | None:
    container = _find_by_testid(soup, "hero-summary-developer")
    if container is None:
        return None
    link = container.find("a")
    text = link.get_text() if link else container.get_text()
    collapsed = _collapse(text.replace("Developer:", ""))
    return collapsed or None


def parse_game_detail(html: str, expected_url: str) -> GameDTO:
    soup = BeautifulSoup(html, "html.parser")
    _require_matching_canonical(soup, expected_url)
    ld = _extract_json_ld(soup)
    title = ld.get("name")
    url = ld.get("url")
    if not isinstance(title, str) or not title.strip():
        raise MetacriticParseError("JSON-LD is missing a non-empty title")
    if not isinstance(url, str) or not url.strip():
        raise MetacriticParseError("JSON-LD is missing a canonical url")
    canonical_locator = urlsplit(url).path

    payload = _extract_nuxt_payload(soup)
    game_record = _find_game_record(payload, _slug_from_url(expected_url))
    source_game_id = _resolve(payload, game_record.get("id"))
    if not isinstance(source_game_id, (str, int)) or not str(source_game_id):
        raise MetacriticParseError("__NUXT_DATA__ game record is missing an id")

    platform_list_index = game_record.get("platforms")
    platform_indices = _resolve(payload, platform_list_index)
    if not isinstance(platform_indices, list) or not platform_indices:
        raise MetacriticParseError("Game has zero platforms")
    platforms = [
        _parse_platform(payload, record)
        for record in (_resolve(payload, i) for i in platform_indices)
        if isinstance(record, dict)
    ]
    if not platforms:
        raise MetacriticParseError("Game has zero resolvable platforms")

    lead_userscore = _extract_user_score(soup)
    if lead_userscore is not None:
        platforms = [
            p if not p.is_lead_platform else _with_userscore(p, lead_userscore) for p in platforms
        ]

    cover_url = _safe_url(ld.get("image"))
    raw_description = ld.get("description")
    description = raw_description if isinstance(raw_description, str) else None
    trailer = ld.get("trailer")
    video_embed_url = None
    video_content_url = None
    if isinstance(trailer, dict):
        video_embed_url = _safe_url(trailer.get("embedUrl"))
        video_content_url = _safe_url(trailer.get("contentUrl"))

    return GameDTO(
        source_game_id=str(source_game_id),
        canonical_locator=canonical_locator,
        title=_collapse(title),
        cover_url=cover_url,
        developer=_extract_developer(soup),
        description=description,
        video_embed_url=video_embed_url,
        video_content_url=video_content_url,
        platforms=tuple(platforms),
    )


def _with_userscore(platform: GamePlatformDTO, userscore: Decimal) -> GamePlatformDTO:
    return GamePlatformDTO(
        source_platform_id=platform.source_platform_id,
        source_game_platform_id=platform.source_game_platform_id,
        slug=platform.slug,
        name=platform.name,
        is_lead_platform=platform.is_lead_platform,
        metascore=platform.metascore,
        userscore=userscore,
        critic_reviews_path=platform.critic_reviews_path,
        user_reviews_path=platform.user_reviews_path,
    )


def _extract_user_score(soup: BeautifulSoup) -> Decimal | None:
    # bs4-stubs' attrs-only find_all() overloads are stricter than the runtime signature.
    tags = soup.find_all(attrs={"title": True})  # type: ignore[call-overload]
    for tag in tags:
        if not isinstance(tag, Tag):
            continue
        title = tag.get("title")
        if not isinstance(title, str):
            continue
        match = _USER_SCORE_TITLE.match(title.strip())
        if match:
            try:
                return Decimal(match.group(1))
            except InvalidOperation:  # pragma: no cover - regex already restricts the shape
                return None
    return None


def parse_platform_userscore(html: str, expected_url: str) -> Decimal | None:
    """Extract one platform's Userscore from its `/user-reviews/?platform=<slug>` page.

    Returns ``None`` for a genuinely-empty score widget (natural absence, not an error);
    raises when the expected score-card container is absent entirely (structurally invalid page)
    or when the page's own canonical URL does not match the platform that was requested.
    """
    soup = BeautifulSoup(html, "html.parser")
    _require_matching_canonical(soup, expected_url)
    score = _extract_user_score(soup)
    if score is not None:
        return score
    if _find_by_testid(soup, "score-card-overview") is not None:
        return None
    if _find_by_testid(soup, "global-score-wrapper") is not None:
        return None
    raise MetacriticParseError("Missing the platform user-reviews score widget")


_GAME_HREF = re.compile(r"/game/([a-z0-9][a-z0-9-]*)/?$")


def _slug_from_href(href: object) -> str | None:
    if not isinstance(href, str):
        return None
    match = _GAME_HREF.search(urlsplit(href).path)
    return match.group(1) if match else None


def _find_game_title_by_slug(payload: list[object], slug: str) -> dict[str, object] | None:
    for value in payload:
        if not isinstance(value, dict) or "type" not in value:
            continue
        if _resolve(payload, value["type"]) != "game-title":
            continue
        if _resolve(payload, value.get("slug")) == slug:
            return value
    return None


def _identity_from_slug(payload: list[object], slug: str) -> GameIdentityDTO:
    record = _find_game_title_by_slug(payload, slug)
    if record is None:
        raise MetacriticParseError(f"__NUXT_DATA__ has no game-title record for slug {slug!r}")
    source_game_id = _resolve(payload, record.get("id"))
    title = _resolve(payload, record.get("title"))
    if not isinstance(source_game_id, (str, int)) or not str(source_game_id):
        raise MetacriticParseError(f"game-title record for slug {slug!r} is missing an id")
    if not isinstance(title, str) or not title.strip():
        raise MetacriticParseError(f"game-title record for slug {slug!r} is missing a title")
    return GameIdentityDTO(
        source_game_id=str(source_game_id),
        canonical_locator=f"/game/{slug}/",
        title=_collapse(title),
    )


def parse_new_releases(html: str, expected_url: str) -> list[GameIdentityDTO]:
    """The homepage's `aria-label="New Releases content"` carousel, in source order.

    List cards give identity (id/slug/title) only — not the full `GameDTO`, which still needs
    its own `parse_game_detail` fetch (`SEL-01`: up to 20 positions, no SEE ALL fallback here).
    """
    soup = BeautifulSoup(html, "html.parser")
    _require_matching_canonical(soup, expected_url)
    section = _find_by_attr(soup, None, "aria-label", "New Releases content")
    if section is None:
        raise MetacriticParseError('Missing the "New Releases content" section')
    payload = _extract_nuxt_payload(soup)
    slugs: list[str] = []
    for tag in _find_all_by_attr(section, "data-testid", "product-card-content"):
        slug = _slug_from_href(tag.get("href"))
        if slug is None:
            raise MetacriticParseError(f"Unrecognised New Releases card href: {tag.get('href')!r}")
        slugs.append(slug)
    if not slugs:
        raise MetacriticParseError("New Releases section has zero cards")
    return [_identity_from_slug(payload, slug) for slug in slugs]


def _require_matching_browse_listing(soup: BeautifulSoup, expected_url: str) -> None:
    """Confirmed live on pages 1, 2 and 7429 of the same listing: every SEE ALL page's
    canonical/og:url is the bare listing URL with no `?page=` query string at all — unlike the
    game-detail/platform pages, this listing cannot be canonically distinguished by page number.
    So this only confirms the response is *a* page of the intended listing (catches a genuinely
    unrelated page), not the specific page number requested; a wrong/duplicate page instead is
    already handled safely by this module's identity-based dedup, not by canonical matching."""
    canonical = _extract_canonical_url(soup)
    if canonical is None:
        raise MetacriticParseError("Page has no canonical/og:url to verify its identity")
    expected_path = urlsplit(expected_url).path.rstrip("/")
    canonical_path = urlsplit(canonical).path.rstrip("/")
    if canonical_path != expected_path:
        raise MetacriticParseError(
            f"Page canonical {canonical!r} is not the requested listing {expected_url!r}"
        )


def parse_browse_page(html: str, expected_url: str) -> BrowsePage:
    """One SEE ALL ("Newest" sort) page: identities in source order, plus whether a next page
    exists (`pagination-arrow-next` without the `--disabled` modifier class, confirmed live)."""
    soup = BeautifulSoup(html, "html.parser")
    _require_matching_browse_listing(soup, expected_url)
    payload = _extract_nuxt_payload(soup)
    slugs: list[str] = []
    for title_tag in _find_all_by_attr(soup, "data-testid", "product-title"):
        anchor = title_tag.find_parent("a")
        href = anchor.get("href") if anchor is not None else None
        slug = _slug_from_href(href)
        if slug is None:
            raise MetacriticParseError(f"Unrecognised browse card href: {href!r}")
        slugs.append(slug)
    games = [_identity_from_slug(payload, slug) for slug in slugs]

    next_arrow = _find_by_attr(soup, None, "data-testid", "pagination-arrow-next")
    if next_arrow is None:
        raise MetacriticParseError("Missing the pagination next-page control")
    raw_classes = next_arrow.get("class")
    classes: list[str]
    if isinstance(raw_classes, str):
        classes = raw_classes.split()
    elif isinstance(raw_classes, list):
        classes = [str(item) for item in raw_classes]
    else:
        classes = []
    has_next_page = not any("disabled" in cls for cls in classes)
    return BrowsePage(games=tuple(games), has_next_page=has_next_page)
