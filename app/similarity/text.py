"""Similar games from saved text: `text-hybrid` 3.0.0 (dense embedding + TF-IDF, fused per query).

Pure numpy ranking over already-saved data: no ORM, HTTP, model or provider calls. The embedding
vectors are produced elsewhere (`catalog.similarity_index`); this module only turns saved games and
their vectors into ranked, explained neighbours, deterministically.

Why text and not genre Jaccard (`similarity.policy`): the source labels each game with exactly one
genre out of ~80 narrow ones, so Jaccard is 1 or 0 and the order inside a genre falls back to the
alphabet (`evals/similarity/text_report.json`: nDCG@5 0.19 against 0.71 for text).

Why 3.0.0 (`evals/similarity/text_report_v2.json`, ADR-0003): about a quarter of the catalogue
carries a legacy mobile-app description that belongs to another game (a "third person shooter"
described as a slot machine), and 2.0.0 matched those games by that foreign text. Now:

* a description is used only if it passes `description_problem` (no app-store boilerplate, no
  stripped-emoji `?` runs, does not introduce itself as a differently named game);
* a game whose description is used is compared, by title, genre and description, only with other
  such games - exactly the 2.0.0 fusion (each query's dense cosine row and TF-IDF cosine row are
  z-scored and summed);
* a game without a usable description is compared with every game by its title and genre alone
  (same fusion over the short label text), instead of getting no similar games or foreign ones;
* sharing a genre adds `GENRE_BONUS`; a neighbour is kept only if the score reaches
  `MIN_FUSED_SCORE`, so a game with no real peer shows fewer than five results, or none.

Each neighbour records why it was chosen (`shared_genre`, `shared_terms`, `basis`) for the page.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

POLICY_ID = "text-hybrid"
POLICY_VERSION = "3.0.0"
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MAX_RESULTS = 5
MAX_TEXT_CHARS = 1200
MIN_DESCRIPTION_CHARS = 40
TFIDF_WEIGHT = 1.0
GENRE_BONUS = 1.0
MIN_FUSED_SCORE = 3.5
MAX_SHARED_TERMS = 3

BASIS_DESCRIPTION = "description"
BASIS_TITLE = "title"

_TOKEN = re.compile(r"[a-z0-9']{3,}")
_STOPWORDS = frozenset(
    "the and for with you your that this are from have will can into their has who its all one "
    "out new game games play player players world its more not but they his her over each like "
    "get any time also which where when while what about them than then only other most many "
    "how via just use such our".split()
)
# Boilerplate of legacy mobile-app listings, and `?` left where emoji were stripped.
_APP_LISTING = re.compile(
    r"\b(?:iphone|ipad|ipod|itunes|app ?store|game ?center|retina|ios|android|apps?|appoday|"
    r"facebook)\b|free for a limited time|limited time only|for free today|free to download|"
    r"\bdownload\b|\?{2,}|(?:^|[\s(])\?(?=[A-Za-z0-9])|^\W*\?\s",
    re.IGNORECASE,
)
# "Skatpalast offers you Skat...", "Fly Survivor is a simple game..." under another title.
_SELF_INTRODUCTION = re.compile(
    r"^\W*((?:[A-Z0-9][\w'’&-]*\s+){0,4}[A-Z0-9][\w'’&-]*)\s+"
    r"(?:(?:is|are)\s+(?:a|an|the)\b|offers\b|lets\b)"
)
_NOT_A_NAME = frozenset("this the it our your you a an welcome there here".split())
# Shown reasons only (scores are unaffected): generic words that explain nothing to a reader.
_VAGUE = frozenset(
    "absolutely after again always amazing another back become beautiful best better big can't "
    "come complete cool different easy enjoy even ever every experience fast find first free fun "
    "gameplay good great hard help here hours keep know last level levels little look lots made "
    "make mode much must need never next only over person real right same see she still take "
    "than there things third three through today together unique very want way well will without "
    "work epic crazy "
    "you'll your".split()
)


@dataclass(frozen=True, slots=True)
class Neighbor:
    game_id: int
    score: float
    shared_genre: bool = False
    shared_terms: tuple[str, ...] = ()
    basis: str = BASIS_DESCRIPTION


@dataclass(frozen=True, slots=True)
class Item:
    """One saved game: its label (title and genre) and, if usable, its full text."""

    game_id: int
    genres: tuple[str, ...]
    label_text: str
    label_vector: np.ndarray
    text: str | None = None
    vector: np.ndarray | None = None


def has_signal(description: str | None) -> bool:
    """A game with (almost) no description carries no text to compare."""
    return description is not None and len(description.strip()) >= MIN_DESCRIPTION_CHARS


def _squash(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def description_problem(title: str, description: str | None) -> str | None:
    """Why the saved description should not describe this game, or `None` when it can.

    The markers are deliberately literal so a reader can check each verdict: an empty or very
    short text, app-store boilerplate, or an opening that introduces a differently named game.
    """
    if description is None or not has_signal(description):
        return "no description"
    if match := _APP_LISTING.search(description):
        return f"app listing text ({match.group(0).strip()})"
    if match := _SELF_INTRODUCTION.match(description):
        name = match.group(1)
        squashed, own = _squash(name), _squash(title)
        name_words = set(_TOKEN.findall(name.lower()))
        if (
            name.split()[0].lower() not in _NOT_A_NAME
            and len(squashed) >= 3
            and squashed not in own
            and own not in squashed
            and not name_words & set(_TOKEN.findall(title.lower()))
        ):
            return f"describes another game ({name})"
    return None


def game_text(title: str, genres: tuple[str, ...], description: str) -> str:
    return f"{title}. {', '.join(genres)}. {description}"[:MAX_TEXT_CHARS]


def label_text(title: str, genres: tuple[str, ...]) -> str:
    return f"{title}. {', '.join(genres)}."


def tokenize(text: str) -> list[str]:
    return [word for word in _TOKEN.findall(text.lower()) if word not in _STOPWORDS]


def _tfidf_weights(texts: list[str]) -> list[dict[str, float]]:
    count = len(texts)
    documents = [tokenize(text) for text in texts]
    frequency = Counter(word for document in documents for word in set(document))
    return [
        {
            word: (1 + math.log(occurrences)) * math.log(count / frequency[word])
            for word, occurrences in Counter(document).items()
        }
        for document in documents
    ]


def _tfidf_matrix(weights: list[dict[str, float]]) -> np.ndarray:
    """Cosine similarity matrix of log-tf x idf vectors.

    Norms use every term, but the dense product only spans terms that occur in two or more texts
    (a term seen once cannot contribute to any cross-text similarity), which keeps it small.
    """
    count = len(weights)
    norms = np.array(
        [math.sqrt(sum(value * value for value in row.values())) or 1.0 for row in weights]
    )
    frequency = Counter(word for row in weights for word in row)
    shared = sorted(word for word, seen in frequency.items() if seen >= 2)
    column = {word: index for index, word in enumerate(shared)}
    matrix = np.zeros((count, len(shared)), dtype=np.float32)
    for row_index, row in enumerate(weights):
        for word, value in row.items():
            if (index := column.get(word)) is not None:
                matrix[row_index, index] = value
    return (matrix @ matrix.T) / np.outer(norms, norms)


def tfidf_similarity(texts: list[str]) -> np.ndarray:
    return _tfidf_matrix(_tfidf_weights(texts))


def _zscore(rows: np.ndarray) -> np.ndarray:
    deviation = rows.std(axis=1, keepdims=True)
    deviation[deviation == 0] = 1.0
    return (rows - rows.mean(axis=1, keepdims=True)) / deviation


def _fused(texts: list[str], vectors: np.ndarray) -> tuple[np.ndarray, list[dict[str, float]]]:
    weights = _tfidf_weights(texts)
    dense = vectors @ vectors.T
    return _zscore(dense) + TFIDF_WEIGHT * _zscore(_tfidf_matrix(weights)), weights


def rank_neighbors(
    game_ids: list[int], texts: list[str], vectors: np.ndarray
) -> dict[int, tuple[Neighbor, ...]]:
    """Policy 2.0.0: description-only ranking, kept as the comparison baseline of the evals.

    `vectors` holds one L2-normalised embedding per game, in the same order as `game_ids`.
    """
    if not (len(game_ids) == len(texts) == len(vectors)):
        raise ValueError("game_ids, texts and vectors must have the same length")
    if len(set(game_ids)) != len(game_ids):
        raise ValueError("game_ids must be distinct")
    if len(game_ids) < 2:
        return {game_id: () for game_id in game_ids}
    fused, _ = _fused(texts, vectors)
    np.fill_diagonal(fused, -np.inf)
    identifiers = np.array(game_ids)
    result: dict[int, tuple[Neighbor, ...]] = {}
    for row, game_id in enumerate(game_ids):
        order = np.lexsort((identifiers, -fused[row]))[:MAX_RESULTS]
        result[game_id] = tuple(
            Neighbor(game_id=int(identifiers[index]), score=round(float(fused[row, index]), 3))
            for index in order
            if fused[row, index] >= MIN_FUSED_SCORE
        )
    return result


def _shared_terms(
    first: dict[str, float], second: dict[str, float], hidden: set[str]
) -> tuple[str, ...]:
    common = sorted(
        (
            word
            for word in first.keys() & second.keys()
            if len(word) >= 4 and word not in hidden and word not in _VAGUE
        ),
        key=lambda word: (-first[word] * second[word], word),
    )
    return tuple(common[:MAX_SHARED_TERMS])


def rank(items: list[Item]) -> dict[int, tuple[Neighbor, ...]]:
    """Up to `MAX_RESULTS` explained neighbours per game, best first, ties by saved game ID."""
    game_ids = [item.game_id for item in items]
    if len(set(game_ids)) != len(game_ids):
        raise ValueError("game ids must be distinct")
    if any((item.text is None) != (item.vector is None) for item in items):
        raise ValueError("a game's text and vector must be given together")
    if len(items) < 2:
        return {game_id: () for game_id in game_ids}

    count = len(items)
    genres = [{genre.casefold() for genre in item.genres} for item in items]
    vocabulary = {genre: index for index, genre in enumerate(sorted(set().union(*genres)))}
    membership = np.zeros((count, max(len(vocabulary), 1)), dtype=np.float32)
    for row, labels in enumerate(genres):
        membership[row, [vocabulary[genre] for genre in labels]] = 1.0
    same_genre = (membership @ membership.T > 0).astype(np.float64)
    label_scores, label_weights = _fused(
        [item.label_text for item in items],
        np.stack([item.label_vector for item in items]).astype(np.float32),
    )
    # A lone described game has no described peer, so it is ranked by its label like the rest.
    described = [index for index, item in enumerate(items) if item.text is not None]
    if len(described) < 2:
        described = []
    labelled = sorted(set(range(count)) - set(described))
    scores = np.full((count, count), -np.inf)
    weights: list[dict[str, float]] = list(label_weights)
    if labelled:
        scores[labelled, :] = label_scores[labelled, :]
    if described:
        full_scores, full_weights = _fused(
            [items[index].text or "" for index in described],
            np.stack([items[index].vector for index in described]).astype(np.float32),  # type: ignore[misc]
        )
        scores[np.ix_(described, described)] = full_scores
        for position, index in enumerate(described):
            weights[index] = full_weights[position]
    scores = scores + GENRE_BONUS * same_genre
    np.fill_diagonal(scores, -np.inf)

    identifiers = np.array(game_ids)
    result: dict[int, tuple[Neighbor, ...]] = {}
    by_description = set(described)
    for row, item in enumerate(items):
        basis = BASIS_DESCRIPTION if row in by_description else BASIS_TITLE
        order = np.lexsort((identifiers, -scores[row]))[:MAX_RESULTS]
        neighbours = []
        for col in order:
            if not scores[row, col] >= MIN_FUSED_SCORE:
                continue
            shared = genres[row] & genres[col]
            hidden = {word for genre in genres[row] | genres[col] for word in tokenize(genre)}
            own = label_weights[row] if basis == BASIS_TITLE else weights[row]
            peer = label_weights[col] if basis == BASIS_TITLE else weights[col]
            neighbours.append(
                Neighbor(
                    game_id=int(identifiers[col]),
                    score=round(float(scores[row, col]), 3),
                    shared_genre=bool(shared),
                    shared_terms=_shared_terms(own, peer, hidden),
                    basis=basis,
                )
            )
        result[item.game_id] = tuple(neighbours)
    return result
