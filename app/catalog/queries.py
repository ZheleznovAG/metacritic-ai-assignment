"""Read-only catalog queries for public presentation views.

UI-OPT-01 keeps catalog search/filter/sort in PostgreSQL and exposes a bounded page to the
request path. Detail/similarity queries remain read-only and never perform ranking or enrichment.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import F, Max, Q, QuerySet
from django.db.models.functions import Lower
from similarity import contract as text_policy

from catalog.labels import saved_labels
from catalog.models import Game, GameNeighbors, GamePlatform

CATALOG_PAGE_SIZE = 30

GameListRow = tuple[int, str, str | None, str | None, int | None, date | None]


@dataclass(frozen=True, slots=True)
class PlatformView:
    name: str
    metascore: int | None
    userscore: Decimal | None


@dataclass(frozen=True, slots=True)
class GameDetailView:
    id: int
    title: str
    cover_url: str | None
    developer: str | None
    description: str | None
    video_url: str | None
    platforms: list[PlatformView]
    genres: tuple[str, ...] = ()
    release_date: date | None = None
    publishers: tuple[str, ...] = ()
    content_rating: str | None = None


@dataclass(frozen=True, slots=True)
class GameListItemView:
    id: int
    title: str
    developer: str | None
    cover_url: str | None
    metascore: int | None
    release_date: date | None = None


@dataclass(frozen=True, slots=True)
class CatalogPage:
    items: tuple[GameListItemView, ...]
    number: int
    num_pages: int
    total_count: int
    start_index: int
    end_index: int
    has_previous: bool
    has_next: bool
    previous_number: int | None
    next_number: int | None
    page_numbers: tuple[int | None, ...]


@dataclass(frozen=True, slots=True)
class PlatformOption:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class SimilarGameView:
    id: int
    title: str
    score: float
    genres: tuple[str, ...]
    policy_id: str
    policy_version: str
    shared_genre: bool = False
    shared_terms: tuple[str, ...] = ()
    by_title: bool = False


def _explanation(item: dict[str, object]) -> tuple[bool, tuple[str, ...], bool]:
    """The saved reasons of one neighbour; anything malformed reads as "no reason given"."""
    terms = item.get("terms")
    return (
        item.get("genre") is True,
        tuple(t for t in terms if isinstance(t, str))[: text_policy.MAX_SHARED_TERMS]
        if isinstance(terms, list)
        else (),
        item.get("basis") == text_policy.BASIS_TITLE,
    )


def list_similar_games(game_id: int) -> list[SimilarGameView]:
    """Read the neighbours the worker precomputed (`similarity.text`): one indexed lookup plus one
    fetch of at most five games, with no model, ranking or enrichment on the request path."""
    row = (
        GameNeighbors.objects.filter(game_id=game_id, policy_version=text_policy.POLICY_VERSION)
        .values_list("neighbors", flat=True)
        .first()
    )
    if not isinstance(row, list):
        return []
    scores: dict[int, float] = {}
    reasons: dict[int, tuple[bool, tuple[str, ...], bool]] = {}
    for item in row:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            try:
                scores[item["id"]] = float(item["score"])
            except (TypeError, ValueError):
                continue
            reasons[item["id"]] = _explanation(item)
    games = {
        pk: (title, genres)
        for pk, title, genres in Game.objects.filter(pk__in=list(scores)).values_list(
            "id", "title", "genres"
        )
    }
    return [
        SimilarGameView(
            id=pk,
            title=games[pk][0],
            score=score,
            genres=saved_labels(games[pk][1]),
            policy_id=text_policy.POLICY_ID,
            policy_version=text_policy.POLICY_VERSION,
            shared_genre=reasons[pk][0],
            shared_terms=reasons[pk][1],
            by_title=reasons[pk][2],
        )
        for pk, score in scores.items()
        if pk in games and pk != game_id
    ]


def list_platform_options() -> list[PlatformOption]:
    rows = GamePlatform.objects.order_by("name").values_list("slug", "name").distinct()
    seen: dict[str, str] = {}
    for slug, name in rows:
        seen.setdefault(slug, name)
    return [PlatformOption(slug=slug, name=name) for slug, name in seen.items()]


def _list_game_rows(
    *, query: str = "", platform: str | None = None, sort: str = "score"
) -> QuerySet[Game, GameListRow]:
    """Build the bounded catalog query without hydrating platforms or sorting in Python.

    `ASM-15`: without a platform filter the displayed score is the maximum across all platforms;
    with a filter it is the maximum among matched platforms only. PostgreSQL also performs the
    title/release ordering, so request cost grows with one page rather than the whole catalog.
    """
    games = Game.objects.all()
    if query:
        games = games.filter(title__icontains=query)

    if platform is not None:
        games = games.filter(platforms__slug=platform).annotate(
            _list_metascore=Max(
                "platforms__metascore",
                filter=Q(platforms__slug=platform),
            ),
            _list_title=Lower("title"),
        )
    else:
        games = games.annotate(
            _list_metascore=Max("platforms__metascore"),
            _list_title=Lower("title"),
        )
    if sort == "release":
        games = games.order_by(
            F("release_date").desc(nulls_last=True),
            "_list_title",
            "id",
        )
    else:
        games = games.order_by(
            F("_list_metascore").desc(nulls_last=True),
            "_list_title",
            "id",
        )

    return games.values_list(
        "id",
        "title",
        "developer",
        "cover_url",
        "_list_metascore",
        "release_date",
    )


def _row_to_item(row: GameListRow) -> GameListItemView:
    return GameListItemView(
        id=row[0],
        title=row[1],
        developer=row[2],
        cover_url=row[3],
        metascore=row[4],
        release_date=row[5],
    )


def list_games(
    *, query: str = "", platform: str | None = None, sort: str = "score"
) -> list[GameListItemView]:
    """Compatibility helper used by domain tests; filtering/sorting itself is database-side."""
    return [_row_to_item(row) for row in _list_game_rows(query=query, platform=platform, sort=sort)]


def paginate_games(
    *,
    query: str = "",
    platform: str | None = None,
    sort: str = "score",
    page: str | int | None = None,
    per_page: int = CATALOG_PAGE_SIZE,
) -> CatalogPage:
    """Return one page; invalid numbers fall back to page 1 and oversized values to the last."""
    paginator = Paginator(_list_game_rows(query=query, platform=platform, sort=sort), per_page)
    page_obj = paginator.get_page(page)
    page_numbers = tuple(
        value if isinstance(value, int) else None
        for value in paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    )
    return CatalogPage(
        items=tuple(_row_to_item(row) for row in page_obj.object_list),
        number=page_obj.number,
        num_pages=paginator.num_pages,
        total_count=paginator.count,
        start_index=page_obj.start_index() if paginator.count else 0,
        end_index=page_obj.end_index() if paginator.count else 0,
        has_previous=page_obj.has_previous(),
        has_next=page_obj.has_next(),
        previous_number=page_obj.previous_page_number() if page_obj.has_previous() else None,
        next_number=page_obj.next_page_number() if page_obj.has_next() else None,
        page_numbers=page_numbers,
    )


def get_game_detail(game_id: int) -> GameDetailView | None:
    try:
        game = Game.objects.get(pk=game_id)
    except Game.DoesNotExist:
        return None
    platforms = [
        PlatformView(name=platform.name, metascore=platform.metascore, userscore=platform.userscore)
        for platform in game.platforms.order_by("name")
    ]
    return GameDetailView(
        id=game.id,
        title=game.title,
        cover_url=game.cover_url,
        developer=game.developer,
        description=game.description,
        video_url=game.video_embed_url or game.video_content_url,
        platforms=platforms,
        genres=saved_labels(game.genres),
        release_date=game.release_date,
        publishers=saved_labels(game.publishers),
        content_rating=game.content_rating,
    )
