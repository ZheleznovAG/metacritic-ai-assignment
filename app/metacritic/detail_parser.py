"""Game-detail pages and per-platform user-score pages.

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

import html
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from metacritic.dto import GameDTO, GamePlatformDTO
from metacritic.errors import MetacriticParseError
from metacritic.page import (
    collapse,
    extract_json_ld,
    extract_nuxt_payload,
    find_all_by_attr,
    find_by_testid,
    require_matching_canonical,
    resolve,
    safe_url,
    slug_from_url,
)
from metacritic.validation import metascore as validate_metascore
from metacritic.validation import userscore as validate_userscore

_USER_SCORE_TITLE = re.compile(r"^User score (.*?) out of 10$")


def _find_game_record(payload: list[object], expected_slug: str) -> dict[str, object]:
    # The payload can carry other "game-title"-shaped records (e.g. a "similar games" widget);
    # matching the slug this page was actually requested for avoids picking up the wrong one.
    for value in payload:
        if not isinstance(value, dict) or "platforms" not in value or "type" not in value:
            continue
        if resolve(payload, value["type"]) != "game-title":
            continue
        if resolve(payload, value.get("slug")) == expected_slug:
            return value
    raise MetacriticParseError(
        f"__NUXT_DATA__ payload has no game-title record matching slug {expected_slug!r}"
    )


def _parse_platform(payload: list[object], record: dict[str, object]) -> GamePlatformDTO:
    source_platform_id = resolve(payload, record.get("id"))
    name = resolve(payload, record.get("name"))
    related = resolve(payload, record.get("relatedGameId"))
    slug = resolve(payload, record.get("slug"))
    identity_fields = (source_platform_id, name, slug)
    if not all(isinstance(v, (str, int)) and str(v) for v in identity_fields):
        raise MetacriticParseError("Platform record is missing id/name/slug")
    if not isinstance(related, (str, int)) or not str(related):
        # source_game_platform_id is a mandatory identity assertion (SPK-03), not an optional
        # field: an empty placeholder here would collide across platforms and corrupt identity.
        raise MetacriticParseError("Platform record is missing relatedGameId")
    if "criticScoreSummary" not in record:
        raise MetacriticParseError("Platform record has no criticScoreSummary key")
    critic_summary = resolve(payload, record.get("criticScoreSummary"))
    if not isinstance(critic_summary, dict):
        # Every live-observed platform record carries this as a dict, with `score` itself null
        # for a genuine "tbd" Metascore (research/feasibility/metacritic-contract.md). A record
        # where the container itself is absent/malformed is degraded markup, not a natural
        # absence, and must not be silently reported the same way as a real tbd score. The two
        # messages are kept distinct (key absent vs. wrong shape) so `candidate.last_error` tells
        # an on-call engineer which one actually happened.
        raise MetacriticParseError(
            f"Platform record's criticScoreSummary did not resolve to an object "
            f"(got {type(critic_summary).__name__})"
        )
    raw_score = resolve(payload, critic_summary.get("score"))
    metascore = validate_metascore(raw_score)
    critic_path: str | None = None
    raw_url = resolve(payload, critic_summary.get("url"))
    if isinstance(raw_url, str) and raw_url:
        critic_path = raw_url
    user_path = None
    if critic_path and "critic-reviews" in critic_path:
        user_path = critic_path.replace("critic-reviews", "user-reviews")
    is_lead = bool(resolve(payload, record.get("isLeadPlatform")))
    return GamePlatformDTO(
        source_platform_id=str(source_platform_id),
        source_game_platform_id=str(related),
        slug=str(slug),
        name=collapse(str(name)),
        is_lead_platform=is_lead,
        metascore=metascore,
        userscore=None,
        critic_reviews_path=critic_path,
        user_reviews_path=user_path,
    )


def _extract_developer(soup: BeautifulSoup) -> str | None:
    container = find_by_testid(soup, "hero-summary-developer")
    if container is None:
        return None
    link = container.find("a")
    text = link.get_text() if link else container.get_text()
    collapsed = collapse(text.replace("Developer:", ""))
    return collapsed or None


def parse_game_detail(html: str, expected_url: str) -> GameDTO:
    soup = BeautifulSoup(html, "html.parser")
    require_matching_canonical(soup, expected_url)
    ld = extract_json_ld(soup)
    title = ld.get("name")
    url = ld.get("url")
    if not isinstance(title, str) or not title.strip():
        raise MetacriticParseError("JSON-LD is missing a non-empty title")
    if not isinstance(url, str) or not url.strip():
        raise MetacriticParseError("JSON-LD is missing a canonical url")
    canonical_locator = urlsplit(url).path

    payload = extract_nuxt_payload(soup)
    game_record = _find_game_record(payload, slug_from_url(expected_url))
    source_game_id = resolve(payload, game_record.get("id"))
    if not isinstance(source_game_id, (str, int)) or not str(source_game_id):
        raise MetacriticParseError("__NUXT_DATA__ game record is missing an id")

    platform_list_index = game_record.get("platforms")
    platform_indices = resolve(payload, platform_list_index)
    if not isinstance(platform_indices, list) or not platform_indices:
        raise MetacriticParseError("Game has zero platforms")
    # `MA-02`: the list states how many platforms the game has. One unresolvable entry is
    # corruption, not a platform that disappeared, so the whole response is rejected rather
    # than stored as a seemingly complete shorter list.
    platforms = []
    for index in platform_indices:
        record = resolve(payload, index)
        if not isinstance(record, dict):
            raise MetacriticParseError("Game platform list has an unresolvable entry")
        platforms.append(_parse_platform(payload, record))

    lead_score_containers = find_all_by_attr(soup, "data-testid", "global-score-wrapper")
    if not lead_score_containers:
        # Every live-observed page carries this container even for a genuine "tbd" Userscore
        # (the widget renders with no matching "User score ... out of 10" title inside it, see
        # LiveContractStrayUserScoreWidgetTests). Its total absence is degraded markup, not a
        # natural absence, and must not be silently reported the same way as a real tbd score.
        raise MetacriticParseError("Missing the lead platform's userscore widget container")
    lead_userscore = _extract_user_score(lead_score_containers)
    if lead_userscore is not None:
        platforms = [
            p if not p.is_lead_platform else _with_userscore(p, lead_userscore) for p in platforms
        ]

    cover_url = safe_url(ld.get("image"))
    raw_description = ld.get("description")
    description = _decode_entities(raw_description) if isinstance(raw_description, str) else None
    trailer = ld.get("trailer")
    video_embed_url = None
    video_content_url = None
    if isinstance(trailer, dict):
        video_embed_url = safe_url(trailer.get("embedUrl"))
        video_content_url = safe_url(trailer.get("contentUrl"))

    return GameDTO(
        source_game_id=str(source_game_id),
        canonical_locator=canonical_locator,
        title=collapse(title),
        cover_url=cover_url,
        developer=_extract_developer(soup),
        description=description,
        video_embed_url=video_embed_url,
        video_content_url=video_content_url,
        platforms=tuple(platforms),
        genres=_extract_genres(ld.get("genre")),
        release_date=_extract_release_date(ld.get("datePublished")),
        publishers=_extract_publishers(ld.get("publisher")),
        content_rating=_extract_content_rating(ld.get("contentRating")),
    )


def _decode_entities(text: str) -> str:
    """Some legacy listings arrive entity-encoded (`&bull;`, `&rsquo;`, `&nbsp;`); decode once."""
    return html.unescape(text).replace(" ", " ")


def _extract_release_date(value: object) -> date | None:
    """JSON-LD `datePublished` (`YYYY-MM-DD`). Optional metadata: anything else is absent, never an
    error, so a malformed optional field cannot stop the game from being saved."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _extract_publishers(value: object) -> tuple[str, ...] | None:
    """JSON-LD `publisher`: one organisation or a list of them; names only, duplicates dropped."""
    entries = value if isinstance(value, list) else [value]
    names: list[str] = []
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and (collapsed := collapse(name)) and len(collapsed) <= 255:
            if collapsed not in names:
                names.append(collapsed)
    return tuple(names) or None


def _extract_content_rating(value: object) -> str | None:
    """JSON-LD `contentRating` (an ESRB-style code such as `M`); optional and length-bounded."""
    if not isinstance(value, str):
        return None
    collapsed = collapse(value)
    return collapsed if collapsed and len(collapsed) <= 16 else None


def _extract_genres(value: object) -> tuple[str, ...] | None:
    """Read this VideoGame's JSON-LD genre; absence never fabricates a taxonomy."""
    if value is None:
        return None
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise MetacriticParseError("invalid_genres")
    genres = tuple(collapse(item) for item in values if item.strip())
    if any(len(genre) > 255 or "\x00" in genre for genre in genres):
        raise MetacriticParseError("invalid_genres")
    return genres or None


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


def _extract_user_score(containers: list[BeautifulSoup | Tag]) -> Decimal | None:
    """Reads the "User score ... out of 10" title from within the given hero/score-card
    containers only. The rest of a live page (e.g. individual review cards further down, or a
    site-templating artifact that literally renders "User score null out of 10" outside these
    containers) is not scanned: it can carry unrelated or malformed "User score" titles of its
    own, observed live on games with too few ratings for an aggregate score."""
    tags: list[Tag] = []
    for container in containers:
        # bs4-stubs' attrs-only find_all() overloads are stricter than the runtime signature.
        tags.extend(t for t in container.find_all(attrs={"title": True}) if isinstance(t, Tag))  # type: ignore[call-overload]
    for tag in tags:
        title = tag.get("title")
        if not isinstance(title, str):
            continue
        match = _USER_SCORE_TITLE.match(title.strip())
        if match:
            try:
                return validate_userscore(Decimal(match.group(1)))
            except InvalidOperation as error:
                raise MetacriticParseError("invalid_userscore") from error
    return None


def parse_platform_userscore(html: str, expected_url: str) -> Decimal | None:
    """Extract one platform's Userscore from its `/user-reviews/?platform=<slug>` page.

    Returns ``None`` for a genuinely-empty score widget (natural absence, not an error);
    raises when the expected score-card container is absent entirely (structurally invalid page)
    or when the page's own canonical URL does not match the platform that was requested.
    """
    soup = BeautifulSoup(html, "html.parser")
    require_matching_canonical(soup, expected_url)
    overview_containers = find_all_by_attr(soup, "data-testid", "score-card-overview")
    wrapper_containers = find_all_by_attr(soup, "data-testid", "global-score-wrapper")
    score = _extract_user_score(overview_containers + wrapper_containers)
    if score is not None:
        return score
    if overview_containers or wrapper_containers:
        return None
    raise MetacriticParseError("Missing the platform user-reviews score widget")
