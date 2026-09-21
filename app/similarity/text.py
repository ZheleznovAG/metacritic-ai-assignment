"""Similar games from saved text: `text-hybrid` 2.0.0 (dense embedding + TF-IDF, fused per query).

Pure numpy ranking over already-saved data: no ORM, HTTP, model or provider calls. The embedding
vectors are produced elsewhere (`catalog.similarity_index`); this module only turns
`(ids, texts, vectors)` into ranked neighbours, deterministically.

Why this and not genre Jaccard (`similarity.policy`): the source labels each game with exactly one
genre out of ~80 narrow ones, so Jaccard is 1 or 0 and the order inside a genre falls back to the
alphabet. On 11 hand-graded queries the frozen comparison (`evals/similarity/text_report.json`)
gives nDCG@5 0.19 for genre Jaccard against 0.71 for this policy (threshold included).

Parameters come from that comparison and are not tuned further here:

* the text is title, genre and description, cut to `MAX_TEXT_CHARS`;
* each query's dense cosine row and TF-IDF cosine row are z-scored over the whole catalogue and
  summed (`TFIDF_WEIGHT` on the sparse part);
* a neighbour is kept only if the fused score reaches `MIN_FUSED_SCORE`, so a game with no real
  peer shows fewer than five results, or none, rather than unrelated ones.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

POLICY_ID = "text-hybrid"
POLICY_VERSION = "2.0.0"
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MAX_RESULTS = 5
MAX_TEXT_CHARS = 1200
MIN_DESCRIPTION_CHARS = 40
TFIDF_WEIGHT = 1.0
MIN_FUSED_SCORE = 3.5

_TOKEN = re.compile(r"[a-z0-9']{3,}")
_STOPWORDS = frozenset(
    "the and for with you your that this are from have will can into their has who its all one "
    "out new game games play player players world its more not but they his her over each like "
    "get any time also which where when while what about them than then only other most many "
    "how via just use such our".split()
)


@dataclass(frozen=True, slots=True)
class Neighbor:
    game_id: int
    score: float


def has_signal(description: str | None) -> bool:
    """A game with (almost) no description carries no text to compare, so it takes no part."""
    return description is not None and len(description.strip()) >= MIN_DESCRIPTION_CHARS


def game_text(title: str, genres: tuple[str, ...], description: str) -> str:
    return f"{title}. {', '.join(genres)}. {description}"[:MAX_TEXT_CHARS]


def tokenize(text: str) -> list[str]:
    return [word for word in _TOKEN.findall(text.lower()) if word not in _STOPWORDS]


def tfidf_similarity(texts: list[str]) -> np.ndarray:
    """Cosine similarity matrix of log-tf x idf vectors.

    Norms use every term, but the dense product only spans terms that occur in two or more texts
    (a term seen once cannot contribute to any cross-text similarity), which keeps it small.
    """
    count = len(texts)
    documents = [tokenize(text) for text in texts]
    frequency = Counter(word for document in documents for word in set(document))
    weights = [
        {
            word: (1 + math.log(occurrences)) * math.log(count / frequency[word])
            for word, occurrences in Counter(document).items()
        }
        for document in documents
    ]
    norms = np.array(
        [math.sqrt(sum(value * value for value in row.values())) or 1.0 for row in weights]
    )
    shared = sorted(word for word, seen in frequency.items() if seen >= 2)
    column = {word: index for index, word in enumerate(shared)}
    matrix = np.zeros((count, len(shared)), dtype=np.float32)
    for row_index, row in enumerate(weights):
        for word, value in row.items():
            if (index := column.get(word)) is not None:
                matrix[row_index, index] = value
    return (matrix @ matrix.T) / np.outer(norms, norms)


def _zscore(rows: np.ndarray) -> np.ndarray:
    deviation = rows.std(axis=1, keepdims=True)
    deviation[deviation == 0] = 1.0
    return (rows - rows.mean(axis=1, keepdims=True)) / deviation


def rank_neighbors(
    game_ids: list[int], texts: list[str], vectors: np.ndarray
) -> dict[int, tuple[Neighbor, ...]]:
    """Up to `MAX_RESULTS` neighbours per game, best first, ties broken by the saved game ID.

    `vectors` holds one L2-normalised embedding per game, in the same order as `game_ids`.
    """
    if not (len(game_ids) == len(texts) == len(vectors)):
        raise ValueError("game_ids, texts and vectors must have the same length")
    if len(set(game_ids)) != len(game_ids):
        raise ValueError("game_ids must be distinct")
    if len(game_ids) < 2:
        return {game_id: () for game_id in game_ids}
    dense = vectors @ vectors.T
    fused = _zscore(dense) + TFIDF_WEIGHT * _zscore(tfidf_similarity(texts))
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
