"""Review pages: one page of the critic/user review backend, parsed into review records."""

import json
from urllib.parse import urlsplit

from metacritic.dto import ReviewPageDTO, ReviewRecordDTO
from metacritic.errors import MetacriticParseError


def _require_matching_review_route(
    self_href: str, expected_audience: str, expected_game_slug: str, expected_platform_slug: str
) -> None:
    """The backend echoes the exact requested route in `links.self.href`; comparing paths is
    misroute protection equivalent to `require_matching_canonical` for HTML pages."""
    expected_path = (
        f"/reviews/metacritic/{expected_audience}/games/{expected_game_slug}"
        f"/platform/{expected_platform_slug}/web"
    )
    actual_path = urlsplit(self_href).path
    if actual_path != expected_path:
        raise MetacriticParseError(
            f"Response route {actual_path!r} does not match the requested route {expected_path!r}"
        )


def _parse_review_item(item: object) -> ReviewRecordDTO:
    if not isinstance(item, dict):
        raise MetacriticParseError("Review item is not an object")
    raw_quote = item.get("quote")
    # A real, live-observed fact about this route: a user can submit a score-only review with no
    # written text at all, in which case `quote` is `null` (not merely absent or empty).
    if raw_quote is None:
        quote = ""
    elif isinstance(raw_quote, str):
        quote = raw_quote
    else:
        raise MetacriticParseError("Review item has a non-string quote")
    source_id = item.get("id")
    if source_id is not None and not isinstance(source_id, str):
        raise MetacriticParseError("Review item has a non-string id")
    author = item.get("author")
    publication_slug = item.get("publicationSlug")
    if isinstance(author, str) and author:
        label: str | None = author
    elif isinstance(publication_slug, str):
        label = publication_slug
    else:
        label = None
    score = item.get("score")
    score_label = str(score) if isinstance(score, int) and not isinstance(score, bool) else None
    date_label = item.get("date")
    if date_label is not None and not isinstance(date_label, str):
        raise MetacriticParseError("Review item has a non-string date")
    url = item.get("url")
    external_url = url if isinstance(url, str) else None
    return ReviewRecordDTO(
        source_review_id=source_id,
        author_or_source_label=label,
        score_label=score_label,
        date_label=date_label,
        text=quote,
        external_url=external_url,
    )


def parse_review_page(
    body: str, expected_audience: str, expected_game_slug: str, expected_platform_slug: str
) -> ReviewPageDTO:
    """Parses one backend `.../reviews/metacritic/{audience}/games/{slug}/platform/{slug}/web`
    page. Raises on structural violations rather than returning partial data, same contract as
    `parse_game_detail`."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise MetacriticParseError(f"Response is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise MetacriticParseError("Response body is not a JSON object")
    data = payload.get("data")
    links = payload.get("links")
    if not isinstance(data, dict) or not isinstance(links, dict):
        raise MetacriticParseError("Response is missing data/links")

    self_link = links.get("self")
    self_href = self_link.get("href") if isinstance(self_link, dict) else None
    if not isinstance(self_href, str):
        raise MetacriticParseError("Response is missing links.self.href")
    _require_matching_review_route(
        self_href, expected_audience, expected_game_slug, expected_platform_slug
    )

    reported_total = data.get("totalResults")
    if (
        not isinstance(reported_total, int)
        or isinstance(reported_total, bool)
        or reported_total < 0
    ):
        raise MetacriticParseError("Response has an invalid totalResults")

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise MetacriticParseError("Response is missing data.items")
    items = tuple(_parse_review_item(item) for item in raw_items)

    next_link = links.get("next")
    next_cursor = next_link.get("href") if isinstance(next_link, dict) else None
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise MetacriticParseError("Response has an invalid links.next.href")

    return ReviewPageDTO(items=items, reported_total=reported_total, next_cursor=next_cursor)
