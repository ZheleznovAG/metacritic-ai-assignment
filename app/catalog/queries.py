"""Read-only detail query for the public card (`presentation` never writes catalog rows)."""

from dataclasses import dataclass
from decimal import Decimal

from catalog.models import Game


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
    video_embed_url: str | None
    platforms: list[PlatformView]


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
        video_embed_url=game.video_embed_url,
        platforms=platforms,
    )
