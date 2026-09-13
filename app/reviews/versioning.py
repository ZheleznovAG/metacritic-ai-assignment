"""Immutable review-version identity (R04); content_sha256 still hashes only the text."""

import hashlib
import json


def version_fingerprint(
    text: str, author_label: str | None, score_label: str | None, date_label: str | None
) -> str:
    document = {
        "version": 1,
        "text": text,
        "author": author_label,
        "score": score_label,
        "date": date_label,
    }
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
