"""Worker-side upkeep of the similar-games index (`similarity.text`, policy `text-hybrid`).

Two persisted steps, both idempotent and bounded: (1) embed game texts that have no current
embedding - every game's label (title and genre) and each usable description - a small batch per
call; (2) once nothing is pending, recompute every game's neighbours in one transaction. The web
role only reads `GameNeighbors`; it never loads the model or numpy.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from django.db import transaction
from django.db.models import Count, Max
from processing.clock import Clock
from similarity import text as policy
from similarity.embedder import Embedder, FastEmbedder

from catalog.labels import saved_labels
from catalog.models import Game, GameEmbedding, GameNeighbors

logger = logging.getLogger(__name__)

EMBED_BATCH = 64  # short label texts: a policy upgrade re-embeds every game within minutes
MAINTENANCE_INTERVAL_SECONDS = 60
FULL_CHECK_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class Refresh:
    embedded: int
    pending: int
    rebuilt: int


LABEL = "label"
DESCRIPTION = "description"


def game_texts(game: Game) -> dict[str, str]:
    """The texts to embed for a game: always its label, and its description when usable."""
    genres = saved_labels(game.genres)
    texts = {LABEL: policy.label_text(game.title, genres)}
    if policy.description_problem(game.title, game.description) is None:
        texts[DESCRIPTION] = policy.game_text(game.title, genres, game.description or "")
    return texts


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Catalogue:
    texts: dict[int, dict[str, str]]
    genres: dict[int, tuple[str, ...]]

    def fingerprint(self, game_id: int) -> str:
        """Changes with the model or whenever the game's label or usable description changes."""
        texts = self.texts[game_id]
        return _digest("\n".join((policy.MODEL_ID, texts[LABEL], texts.get(DESCRIPTION, ""))))


def _current_texts() -> _Catalogue:
    texts: dict[int, dict[str, str]] = {}
    genres: dict[int, tuple[str, ...]] = {}
    for game in Game.objects.only("id", "title", "genres", "description").order_by("id"):
        texts[game.id] = game_texts(game)
        genres[game.id] = saved_labels(game.genres)
    return _Catalogue(texts=texts, genres=genres)


def _saved_embeddings() -> dict[tuple[int, str], tuple[str, str]]:
    return {
        (game_id, kind): (model_id, digest)
        for game_id, kind, model_id, digest in GameEmbedding.objects.values_list(
            "game_id", "kind", "model_id", "text_sha256"
        )
    }


def _pending(catalogue: _Catalogue) -> list[tuple[int, str]]:
    saved = _saved_embeddings()
    return [
        (game_id, kind)
        for game_id, texts in catalogue.texts.items()
        for kind, text in sorted(texts.items())
        if saved.get((game_id, kind)) != (policy.MODEL_ID, _digest(text))
    ]


def embed_pending(embedder: Embedder, catalogue: _Catalogue, limit: int = EMBED_BATCH) -> int:
    """Embed up to `limit` texts whose saved embedding is missing or was made from other text."""
    todo = _pending(catalogue)[:limit]
    if not todo:
        return 0
    vectors = embedder.embed([catalogue.texts[game_id][kind] for game_id, kind in todo])
    with transaction.atomic():
        for (game_id, kind), vector in zip(todo, vectors, strict=True):
            GameEmbedding.objects.update_or_create(
                game_id=game_id,
                kind=kind,
                defaults={
                    "model_id": policy.MODEL_ID,
                    "text_sha256": _digest(catalogue.texts[game_id][kind]),
                    "vector": np.asarray(vector, dtype="<f4").tobytes(),
                },
            )
    return len(todo)


def neighbors_stale(catalogue: _Catalogue) -> bool:
    """True when the precomputed neighbours do not reflect the current embeddings."""
    current = GameNeighbors.objects.filter(policy_version=policy.POLICY_VERSION)
    expected = list(catalogue.texts)
    # A missing row, or a game whose texts or model changed (a description that became unusable
    # changes no embedding, yet moves the game to title-and-genre matching), needs a rebuild. No
    # wall-clock comparison: the fingerprints alone say whether the saved neighbours are current.
    saved = dict(current.values_list("game_id", "inputs_sha256"))
    return any(saved.get(game_id) != catalogue.fingerprint(game_id) for game_id in expected)


def _saved_item(game_id: int, catalogue: _Catalogue, vectors: dict[str, np.ndarray]) -> policy.Item:
    texts = catalogue.texts[game_id]
    return policy.Item(
        game_id=game_id,
        genres=catalogue.genres[game_id],
        label_text=texts[LABEL],
        label_vector=vectors[LABEL],
        text=texts.get(DESCRIPTION),
        vector=vectors.get(DESCRIPTION),
    )


def _neighbor_json(neighbor: policy.Neighbor) -> dict[str, object]:
    return {
        "id": neighbor.game_id,
        "score": neighbor.score,
        "genre": neighbor.shared_genre,
        "terms": list(neighbor.shared_terms),
        "basis": neighbor.basis,
    }


UPSERT_BATCH = 500


def rebuild_neighbors(catalogue: _Catalogue, clock: Clock) -> int:
    """Recompute and save the neighbours of every game whose texts all have current embeddings."""
    vectors: dict[int, dict[str, np.ndarray]] = {}
    for game_id, kind, vector, model_id, digest in GameEmbedding.objects.filter(
        game_id__in=list(catalogue.texts)
    ).values_list("game_id", "kind", "vector", "model_id", "text_sha256"):
        text = catalogue.texts[game_id].get(kind)
        if text is not None and (model_id, digest) == (policy.MODEL_ID, _digest(text)):
            vectors.setdefault(game_id, {})[kind] = np.frombuffer(bytes(vector), dtype="<f4")
    ready = [
        game_id
        for game_id in sorted(catalogue.texts)
        if set(catalogue.texts[game_id]) <= set(vectors.get(game_id, {}))
    ]
    ranked = policy.rank([_saved_item(game_id, catalogue, vectors[game_id]) for game_id in ready])
    now = clock.now_utc()
    rows = [
        GameNeighbors(
            game_id=game_id,
            policy_version=policy.POLICY_VERSION,
            neighbors=[_neighbor_json(n) for n in neighbors],
            inputs_sha256=catalogue.fingerprint(game_id),
            computed_at=now,
        )
        for game_id, neighbors in ranked.items()
    ]
    with transaction.atomic():
        for start in range(0, len(rows), UPSERT_BATCH):
            GameNeighbors.objects.bulk_create(
                rows[start : start + UPSERT_BATCH],
                update_conflicts=True,
                unique_fields=["game"],
                update_fields=["policy_version", "neighbors", "inputs_sha256", "computed_at"],
            )
    return len(ranked)


def refresh(embedder: Embedder, clock: Clock, limit: int = EMBED_BATCH) -> Refresh:
    catalogue = _current_texts()
    embedded = embed_pending(embedder, catalogue, limit)
    pending = len(_pending(catalogue)) if embedded else 0
    rebuilt = 0
    if pending == 0 and (embedded or neighbors_stale(catalogue)):
        rebuilt = rebuild_neighbors(catalogue, clock)
    return Refresh(embedded=embedded, pending=pending, rebuilt=rebuilt)


def _catalogue_signature() -> tuple[object, ...]:
    """Two cheap aggregates that change whenever a game is added or saved with new text."""
    games = Game.objects.aggregate(count=Count("id"), latest=Max("updated_at"))
    return (games["count"], games["latest"], GameNeighbors.objects.count())


class Maintainer:
    """Runs `refresh` at most once per interval and never lets a model problem stop the worker."""

    def __init__(
        self,
        embedder_factory: Callable[[], Embedder] = FastEmbedder,
        interval: float = MAINTENANCE_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._factory = embedder_factory
        self._embedder: Embedder | None = None
        self._interval = interval
        self._monotonic = monotonic
        self._next_at = 0.0
        self._settled: tuple[object, ...] | None = None
        self._settled_at = 0.0

    def run_if_due(self, clock: Clock) -> Refresh | None:
        now = self._monotonic()
        if now < self._next_at:
            return None
        try:
            signature = _catalogue_signature()
            if signature == self._settled and now - self._settled_at < FULL_CHECK_SECONDS:
                self._next_at = now + self._interval
                return None
            if self._embedder is None:
                self._embedder = self._factory()
            result = refresh(self._embedder, clock)
        except Exception:
            logger.exception("similar-games upkeep failed; retrying later")
            self._next_at = now + 10 * self._interval
            return None
        # While embeddings are still pending, continue on the next tick instead of waiting.
        self._next_at = now if result.pending else now + self._interval
        if not (result.embedded or result.pending or result.rebuilt):
            self._settled, self._settled_at = signature, now
        else:
            self._settled = None
        return result
