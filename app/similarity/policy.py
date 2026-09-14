"""IMP-06 / SIM-01: genre Jaccard baseline for the frozen comparison."""

from dataclasses import dataclass

from catalog.genres import normalize_genres

POLICY_ID = "genre-jaccard"
POLICY_VERSION = "1.0.0"
MAX_RESULTS = 5


@dataclass(frozen=True, slots=True)
class SavedGame:
    id: int
    title: str
    genres: tuple[str, ...]
    platforms: tuple[str, ...] = ()
    developer: str | None = None


@dataclass(frozen=True, slots=True)
class SimilarGame:
    game_id: int
    score: float
    shared_genres: tuple[str, ...]
    policy_id: str = POLICY_ID
    policy_version: str = POLICY_VERSION


def rank(query_id: int, catalog: tuple[SavedGame, ...]) -> tuple[SimilarGame, ...]:
    """Return up to five distinct saved IDs; missing genres never count as a match.

    Input represents one catalog snapshot with one record per saved primary key.
    Identical repeated records are harmless; conflicting records for one ID are invalid.
    """
    if type(query_id) is not int:
        return ()
    games: dict[int, SavedGame] = {}
    for game in catalog:
        if type(game.id) is not int or game.id <= 0:
            raise ValueError("Saved game IDs must be positive integers")
        if game.id in games and games[game.id] != game:
            raise ValueError("Conflicting saved records for one game ID")
        games[game.id] = game
    query = games.get(query_id)
    if query is None:
        return ()
    genres = frozenset(normalize_genres(query.genres))
    matches = []
    for game in games.values():
        if game.id == query_id:
            continue
        candidate_genres = frozenset(normalize_genres(game.genres))
        shared = genres & candidate_genres
        if shared:
            matches.append(
                SimilarGame(
                    game_id=game.id,
                    score=len(shared) / len(genres | candidate_genres),
                    shared_genres=tuple(sorted(shared)),
                )
            )
    matches.sort(key=lambda item: (-item.score, games[item.game_id].title.casefold(), item.game_id))
    return tuple(matches[:MAX_RESULTS])
