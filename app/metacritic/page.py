"""SSR page primitives shared by every Metacritic parser: JSON-LD, the positionally-indexed
``__NUXT_DATA__`` payload, canonical-URL checks and DOM lookups. No network access happens here."""

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from metacritic.errors import MetacriticParseError


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def safe_url(value: object) -> str | None:
    """Only http(s) URLs are trusted for storage/rendering; anything else (e.g. `javascript:`) is
    treated as absent rather than passed through to a template `href`/`src`."""
    if not isinstance(value, str) or not value:
        return None
    return value if urlsplit(value).scheme in ("http", "https") else None


def resolve(payload: list[object], index: object) -> object:
    if not isinstance(index, int) or isinstance(index, bool) or not (0 <= index < len(payload)):
        return None
    return payload[index]


def slug_from_url(url: str) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]


def extract_canonical_url(soup: BeautifulSoup) -> str | None:
    tag = find_by_attr(soup, "link", "rel", "canonical")
    if tag is not None:
        href = tag.get("href")
        if isinstance(href, str) and href:
            return href
    meta = find_by_attr(soup, "meta", "property", "og:url")
    if meta is not None:
        content = meta.get("content")
        if isinstance(content, str) and content:
            return content
    return None


def require_matching_canonical(soup: BeautifulSoup, expected_url: str) -> None:
    """Guards against a silent redirect/misroute returning a different page than requested
    (e.g. a different platform's score attributed to the one that was asked for). Only used for
    game-detail/platform pages, which are canonically distinguishable per page — unlike the SEE
    ALL listing, see `_require_matching_browse_listing`."""
    canonical = extract_canonical_url(soup)
    if canonical is None:
        raise MetacriticParseError("Page has no canonical/og:url to verify its identity")
    if canonical.rstrip("/") != expected_url.rstrip("/"):
        raise MetacriticParseError(
            f"Page canonical {canonical!r} does not match the requested {expected_url!r}"
        )


def extract_json_ld(soup: BeautifulSoup) -> dict[str, object]:
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


def extract_nuxt_payload(soup: BeautifulSoup) -> list[object]:
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


def find_by_testid(node: BeautifulSoup | Tag, value: str) -> Tag | None:
    return find_by_attr(node, None, "data-testid", value)


def find_by_attr(node: BeautifulSoup | Tag, name: str | None, attr: str, value: str) -> Tag | None:
    # bs4-stubs' find() overloads are stricter than the runtime signature about `name`/`attrs`.
    result = node.find(name, attrs={attr: value})  # type: ignore[arg-type]
    return result if isinstance(result, Tag) else None


def find_all_by_attr(node: BeautifulSoup | Tag, attr: str, value: str) -> list[Tag]:
    # Same bs4-stubs overload strictness as `find_by_attr`, for find_all().
    results = node.find_all(attrs={attr: value})  # type: ignore[call-overload]
    return [tag for tag in results if isinstance(tag, Tag)]
