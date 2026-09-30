"""Listing pages: the New Releases section and the paginated browse listing, parsed into game
identities in source order."""

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from metacritic.dto import BrowsePage, GameIdentityDTO
from metacritic.errors import MetacriticParseError
from metacritic.page import (
    collapse,
    extract_canonical_url,
    extract_nuxt_payload,
    find_all_by_attr,
    find_by_attr,
    require_matching_canonical,
    resolve,
)

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
        if resolve(payload, value["type"]) != "game-title":
            continue
        if resolve(payload, value.get("slug")) == slug:
            return value
    return None


def _identity_from_slug(payload: list[object], slug: str) -> GameIdentityDTO:
    record = _find_game_title_by_slug(payload, slug)
    if record is None:
        raise MetacriticParseError(f"__NUXT_DATA__ has no game-title record for slug {slug!r}")
    source_game_id = resolve(payload, record.get("id"))
    title = resolve(payload, record.get("title"))
    if not isinstance(source_game_id, (str, int)) or not str(source_game_id):
        raise MetacriticParseError(f"game-title record for slug {slug!r} is missing an id")
    if not isinstance(title, str) or not title.strip():
        raise MetacriticParseError(f"game-title record for slug {slug!r} is missing a title")
    return GameIdentityDTO(
        source_game_id=str(source_game_id),
        canonical_locator=f"/game/{slug}/",
        title=collapse(title),
    )


def parse_new_releases(html: str, expected_url: str) -> list[GameIdentityDTO]:
    """The homepage's `aria-label="New Releases content"` carousel, in source order.

    List cards give identity (id/slug/title) only — not the full `GameDTO`, which still needs
    its own `parse_game_detail` fetch (`SEL-01`: up to 20 positions, no SEE ALL fallback here).
    """
    soup = BeautifulSoup(html, "html.parser")
    require_matching_canonical(soup, expected_url)
    section = find_by_attr(soup, None, "aria-label", "New Releases content")
    if section is None:
        raise MetacriticParseError('Missing the "New Releases content" section')
    payload = extract_nuxt_payload(soup)
    slugs: list[str] = []
    for tag in find_all_by_attr(section, "data-testid", "product-card-content"):
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
    canonical = extract_canonical_url(soup)
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
    payload = extract_nuxt_payload(soup)
    slugs: list[str] = []
    for title_tag in find_all_by_attr(soup, "data-testid", "product-title"):
        anchor = title_tag.find_parent("a")
        href = anchor.get("href") if anchor is not None else None
        slug = _slug_from_href(href)
        if slug is None:
            raise MetacriticParseError(f"Unrecognised browse card href: {href!r}")
        slugs.append(slug)
    games = [_identity_from_slug(payload, slug) for slug in slugs]

    next_arrow = find_by_attr(soup, None, "data-testid", "pagination-arrow-next")
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
