"""IMP-06 comparison adapters. Neither policy sees case IDs or relevance judgments."""

from contract import SavedGame
from catalog.genres import normalize_label
from similarity import policy


def genre_jaccard(query_id: int, catalog: tuple[SavedGame, ...]) -> list[int]:
    saved = tuple(policy.SavedGame(g.id, g.title, g.genres, g.platforms, g.developer) for g in catalog)
    return [item.game_id for item in policy.rank(query_id, saved)]


def weighted_metadata(query_id: int, catalog: tuple[SavedGame, ...]) -> list[int]:
    """Design candidate 0.1.0, unmodified weights/eligibility from docs/design.md."""
    query = next((g for g in catalog if g.id == query_id), None)
    if query is None:
        return []

    def features(values):
        return {label for value in values if (label := normalize_label(value))}

    def jaccard(left, right):
        return len(left & right) / len(left | right) if left or right else 0.0

    genres, platforms = features(query.genres), features(query.platforms)
    developer = normalize_label(query.developer or "")
    ranked = []
    for game in catalog:
        if game.id == query_id:
            continue
        other_genres = features(game.genres)
        same_developer = bool(developer and developer == normalize_label(game.developer or ""))
        score = (0.60 * jaccard(genres, other_genres)
                 + 0.25 * jaccard(platforms, features(game.platforms))
                 + 0.15 * same_developer)
        if (genres & other_genres or same_developer) and score >= 0.15:
            ranked.append((score, game.title.casefold(), game.id))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [item[2] for item in ranked[:5]]
