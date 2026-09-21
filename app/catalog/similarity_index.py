"""Worker-side upkeep of the similar-games index (`similarity.text`, policy `text-hybrid`).

Two persisted steps, both idempotent and bounded: (1) embed games whose text has no current
embedding, a small batch per call; (2) once nothing is pending, recompute every game's neighbours
in one transaction. The web role only reads `GameNeighbors`; it never loads the model or numpy.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from django.db import transaction
from django.db.models import Count, Max, Min
from processing.clock import Clock
from similarity import text as policy
from similarity.embedder import Embedder, FastEmbedder

from catalog.labels import saved_labels
from catalog.models import Game, GameEmbedding, GameNeighbors

logger = logging.getLogger(__name__)

EMBED_BATCH = 16
MAINTENANCE_INTERVAL_SECONDS = 60
FULL_CHECK_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class Refresh:
    embedded: int
    pending: int
    rebuilt: int


def game_text(game: Game) -> str | None:
    """The comparison text, or `None` when the game has too little description to compare."""
    if game.description is None or not policy.has_signal(game.description):
        return None
    return policy.game_text(game.title, saved_labels(game.genres), game.description)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _current_texts() -> dict[int, str]:
    texts: dict[int, str] = {}
    for game in Game.objects.only("id", "title", "genres", "description").order_by("id"):
        if (text := game_text(game)) is not None:
            texts[game.id] = text
    return texts


def _saved_embeddings() -> dict[int, tuple[str, str]]:
    return {
        game_id: (model_id, digest)
        for game_id, model_id, digest in GameEmbedding.objects.values_list(
            "game_id", "model_id", "text_sha256"
        )
    }


def _pending(texts: dict[int, str]) -> list[int]:
    saved = _saved_embeddings()
    return [
        game_id
        for game_id, text in texts.items()
        if saved.get(game_id) != (policy.MODEL_ID, _digest(text))
    ]


def embed_pending(embedder: Embedder, texts: dict[int, str], limit: int = EMBED_BATCH) -> int:
    """Embed up to `limit` games whose saved embedding is missing or was made from other text."""
    todo = _pending(texts)[:limit]
    if not todo:
        return 0
    vectors = embedder.embed([texts[game_id] for game_id in todo])
    with transaction.atomic():
        for game_id, vector in zip(todo, vectors, strict=True):
            GameEmbedding.objects.update_or_create(
                game_id=game_id,
                defaults={
                    "model_id": policy.MODEL_ID,
                    "text_sha256": _digest(texts[game_id]),
                    "vector": np.asarray(vector, dtype="<f4").tobytes(),
                },
            )
    return len(todo)


def neighbors_stale(texts: dict[int, str]) -> bool:
    """True when the precomputed neighbours do not reflect the current embeddings."""
    current = GameNeighbors.objects.filter(policy_version=policy.POLICY_VERSION)
    expected = list(texts)
    if set(expected) - set(current.values_list("game_id", flat=True)):
        return True
    # A game that lost its text keeps its row (the worker cannot DELETE) but must not keep showing
    # old neighbours; once emptied it no longer counts as stale.
    if current.exclude(game_id__in=expected).exclude(neighbors=[]).exists():
        return True
    if not expected:
        return False
    newest_embedding = GameEmbedding.objects.aggregate(latest=Max("updated_at"))["latest"]
    oldest_neighbors = current.filter(game_id__in=expected).aggregate(oldest=Min("computed_at"))[
        "oldest"
    ]
    return bool(newest_embedding and oldest_neighbors and newest_embedding > oldest_neighbors)


UPSERT_BATCH = 500


def rebuild_neighbors(texts: dict[int, str], clock: Clock) -> int:
    """Recompute and save the neighbours of every game that has a current embedding."""
    vectors_by_game = {
        game_id: np.frombuffer(bytes(vector), dtype="<f4")
        for game_id, vector, model_id, digest in GameEmbedding.objects.filter(
            game_id__in=list(texts)
        ).values_list("game_id", "vector", "model_id", "text_sha256")
        if (model_id, digest) == (policy.MODEL_ID, _digest(texts[game_id]))
    }
    game_ids = sorted(vectors_by_game)
    ranked: dict[int, tuple[policy.Neighbor, ...]] = {}
    if game_ids:
        ranked = policy.rank_neighbors(
            game_ids,
            [texts[game_id] for game_id in game_ids],
            np.stack([vectors_by_game[game_id] for game_id in game_ids]).astype(np.float32),
        )
    now = clock.now_utc()
    rows = [
        GameNeighbors(
            game_id=game_id,
            policy_version=policy.POLICY_VERSION,
            neighbors=[{"id": n.game_id, "score": n.score} for n in neighbors],
            computed_at=now,
        )
        for game_id, neighbors in ranked.items()
    ]
    # Games that dropped out (no description any more) get an empty, current row.
    leftovers = set(GameNeighbors.objects.values_list("game_id", flat=True)) - set(ranked)
    rows += [
        GameNeighbors(
            game_id=game_id, policy_version=policy.POLICY_VERSION, neighbors=[], computed_at=now
        )
        for game_id in sorted(leftovers)
    ]
    with transaction.atomic():
        for start in range(0, len(rows), UPSERT_BATCH):
            GameNeighbors.objects.bulk_create(
                rows[start : start + UPSERT_BATCH],
                update_conflicts=True,
                unique_fields=["game"],
                update_fields=["policy_version", "neighbors", "computed_at"],
            )
    return len(ranked)


def refresh(embedder: Embedder, clock: Clock, limit: int = EMBED_BATCH) -> Refresh:
    texts = _current_texts()
    embedded = embed_pending(embedder, texts, limit)
    pending = len(_pending(texts)) if embedded else 0
    rebuilt = 0
    if pending == 0 and (embedded or neighbors_stale(texts)):
        rebuilt = rebuild_neighbors(texts, clock)
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
