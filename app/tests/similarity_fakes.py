"""Deterministic stand-in for the sentence model: hashed bag of words, L2-normalised.

Texts that share words get similar vectors, so tests can build meaningful "clusters" without
loading the real ONNX model or touching the network.
"""

import hashlib

import numpy as np
from similarity.text import tokenize

DIMENSIONS = 64


class BagOfWordsEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        rows = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in tokenize(text):
                bucket = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big")
                rows[row, bucket % DIMENSIONS] += 1.0
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return rows / norms


class ExplodingEmbedder:
    def embed(self, texts: list[str]) -> np.ndarray:
        raise RuntimeError("model unavailable")
