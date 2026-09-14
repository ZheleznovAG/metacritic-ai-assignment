"""SIM-EVAL-01: model-independent saved-catalog boundary; no labels reach the ranker."""

from dataclasses import dataclass
from typing import Callable

MAX_RESULTS = 5


@dataclass(frozen=True, slots=True)
class SavedGame:
    id: int
    title: str
    genres: tuple[str, ...]
    platforms: tuple[str, ...]
    developer: str | None


Ranker = Callable[[int, tuple[SavedGame, ...]], list[int] | tuple[int, ...]]


def catalog_from_case(case: dict) -> tuple[SavedGame, ...]:
    return tuple(SavedGame(
        id=game["id"], title=game["title"], genres=tuple(game["genres"]),
        platforms=tuple(game["platforms"]), developer=game["developer"],
    ) for game in case["catalog"])
