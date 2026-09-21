"""Sentence embedder used by the `text-hybrid` similar-games policy.

No Django, database or network dependency at import time. `fastembed` is imported lazily on first
use, and the ONNX model is expected in the image's baked cache (`FASTEMBED_CACHE_PATH`).
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import numpy as np

from similarity.text import MODEL_ID

BATCH_SIZE = 16


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray:
        """One L2-normalised float32 row per text."""
        ...


class FastEmbedder:
    """ONNX sentence embedder (`fastembed`); the model is baked into the image at build time."""

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self.model_id = model_id
        self._model: Any = None

    def _load(self) -> Any:
        from fastembed import TextEmbedding

        cache = os.environ.get("FASTEMBED_CACHE_PATH") or None
        try:
            return TextEmbedding(self.model_id, cache_dir=cache, local_files_only=True)
        except Exception:
            # Development convenience only: a production image must already contain the model.
            if os.environ.get("APP_ENV") == "production":
                raise
            return TextEmbedding(self.model_id, cache_dir=cache)

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            self._model = self._load()
        rows = np.array(list(self._model.embed(texts, batch_size=BATCH_SIZE)), dtype=np.float32)
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return rows / norms
