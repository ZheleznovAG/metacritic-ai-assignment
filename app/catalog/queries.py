"""Read-only detail query for the public card (`presentation` never writes catalog rows)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from similarity.policy import SavedGame, rank

from catalog.models import Game, GamePlatform


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


@dataclass(frozen=True, slots=True)
class PlatformOption:
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class SimilarGameView:
    id: int
    title: str
    score: float
    shared_genres: tuple[str, ...]
    policy_id: str
    policy_version: str


def list_similar_games(game_id: int) -> list[SimilarGameView]:
    """SIM-VER-01: rank one saved snapshot, without enrichment or platform joins."""
    saved = tuple(
        SavedGame(id=pk, title=title, genres=_saved_genres(genres))
        for pk, title, genres in Game.objects.values_list("id", "title", "genres")
    )
    titles = {game.id: game.title for game in saved}
    return [
        SimilarGameView(
            id=result.game_id,
            title=titles[result.game_id],
            score=result.score,
            shared_genres=result.shared_genres,
            policy_id=result.policy_id,
            policy_version=result.policy_version,
        )
        for result in rank(game_id, saved)
    ]


def _saved_genres(value: object) -> tuple[str, ...]:
    # Corrupt/manual JSON is unknown, never a string split into fake genre letters.
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return ()
    return tuple(value)


def list_platform_options() -> list[PlatformOption]:
    rows = GamePlatform.objects.order_by("name").values_list("slug", "name").distinct()
    seen: dict[str, str] = {}
    for slug, name in rows:
        seen.setdefault(slug, name)
    return [PlatformOption(slug=slug, name=name) for slug, name in seen.items()]


def list_games(*, query: str = "", platform: str | None = None) -> list[GameListItemView]:
    """`ASM-15`: no filter -> Metascore is the max across all of a game's platforms; with a
    platform filter -> the max among only the matched platform(s); a game with no scored platform
    sorts after every scored game; ties sort by title (casefolded)."""
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
            )
        )

    items.sort(
        key=lambda item: (item.metascore is None, -(item.metascore or 0), item.title.casefold())
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
        genres=_saved_genres(game.genres),
        release_date=game.release_date,
        publishers=_saved_genres(game.publishers),
        content_rating=game.content_rating,
    )
