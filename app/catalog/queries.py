"""Read-only detail query for the public card (`presentation` never writes catalog rows)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from similarity import text as text_policy

from catalog.labels import saved_labels
from catalog.models import Game, GameNeighbors, GamePlatform


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


def list_games(
    *, query: str = "", platform: str | None = None, sort: str = "score"
) -> list[GameListItemView]:
    """`ASM-15`: no filter -> Metascore is the max across all of a game's platforms; with a
    platform filter -> the max among only the matched platform(s); a game with no scored platform
    sorts after every scored game; ties sort by title (casefolded). `sort="release"` orders by
    release date, newest first, games without a date last, then by title."""
    games = Game.objects.all()
    if query:
        games = games.filter(title__icontains=query)
    games = games.prefetch_related("platforms")

    items: list[GameListItemView] = []
    for game in games:
        platforms = list(game.platforms.all())
        if platform is not None:
            platforms = [p for p in platforms if p.slug == platform]
            if not platforms:
                continue
        scores = [p.metascore for p in platforms if p.metascore is not None]
        metascore = max(scores) if scores else None
        items.append(
            GameListItemView(
                id=game.id,
                title=game.title,
                developer=game.developer,
                cover_url=game.cover_url,
                metascore=metascore,
                release_date=game.release_date,
            )
        )

    if sort == "release":
        items.sort(
            key=lambda item: (
                item.release_date is None,
                -(item.release_date.toordinal() if item.release_date else 0),
                item.title.casefold(),
            )
        )
    else:
        items.sort(
            key=lambda item: (
                item.metascore is None,
                -(item.metascore or 0),
                item.title.casefold(),
            )
        )
    return items


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
