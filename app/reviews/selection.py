"""ASM-16 candidate `1.0.0` bounded review selection — the exact algorithm `REV-EVAL-01` accepts.

The dataclasses here are field-for-field identical to `evals/review_selection/contract.py`'s frozen
shapes, deliberately duplicated rather than cross-imported: this module ships in the production
image and must not depend on the `evals/` tree at runtime, and the eval harness must not depend on
Django. `evals/review_selection/verify_candidate.py` adapts between the two identical shapes to run
the frozen scorer against this real implementation without touching the frozen oracle files.

Algorithm (`docs/design.md` corpus-building step 1-4, `research/feasibility/game-identity.md`,
`ASM-16`): cross-platform dedup by canonical fingerprint; within each platform, sort by
SHA-256(policy_version + identity_key); round-robin across platforms ordered by platform_slug
(a stable per-platform key, standing in for design.md's `source_platform_id` — this module's pool
only carries the slug); take up to 10; each selected review's input text is capped at 450
`o200k_harmony` tokens with token-boundary truncation, never a semantic rewrite.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import tiktoken

POLICY_VERSION = "1.0.0-candidate"
TOKENIZER_ID = "o200k_harmony"
MAX_SELECTED_REVIEWS = 10
MAX_REVIEW_TOKENS = 450

_ENCODING = tiktoken.get_encoding(TOKENIZER_ID)


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text, disallowed_special=()))


def truncate_to_token_boundary(text: str, max_tokens: int = MAX_REVIEW_TOKENS) -> str:
    token_ids = _ENCODING.encode(text, disallowed_special=())
    return _ENCODING.decode(token_ids[:max_tokens])


class IncompleteCollectionError(Exception):
    """Raised when asked to select from a pool that is not `complete`."""


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    identity_key: str
    platform_slug: str
    page_offset: int
    language: str
    score: float | None
    text: str
    meaningful: bool
    duplicate_of: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionPool:
    audience: str
    game_slug: str
    collection_status: str  # "complete" | "partial"
    reviews: tuple[ReviewRecord, ...]

    @property
    def meaningful_count(self) -> int:
        return sum(1 for review in self.reviews if review.meaningful)


@dataclass(frozen=True, slots=True)
class SelectedReview:
    identity_key: str
    platform_slug: str
    text: str
    truncated: bool
    token_count: int


@dataclass(frozen=True, slots=True)
class SelectionResult:
    selected: tuple[SelectedReview, ...]
    meaningful_pool_count: int
    total_pool_count: int


def _sort_key(identity_key: str) -> str:
    return hashlib.sha256(f"{POLICY_VERSION}:{identity_key}".encode()).hexdigest()


def _deduplicate(reviews: tuple[ReviewRecord, ...]) -> list[ReviewRecord]:
    """One representative per canonical group (`duplicate_of` or its own identity), chosen
    deterministically by the lexicographically smallest identity key in the group."""
    groups: dict[str, list[ReviewRecord]] = {}
    for review in reviews:
        canonical = review.duplicate_of or review.identity_key
        groups.setdefault(canonical, []).append(review)
    representatives = [min(members, key=lambda r: r.identity_key) for members in groups.values()]
    return representatives


def select_reviews(pool: SelectionPool) -> SelectionResult:
    if pool.collection_status != "complete":
        raise IncompleteCollectionError(
            f"pool for {pool.game_slug}/{pool.audience} is {pool.collection_status!r}, not complete"
        )

    deduplicated = _deduplicate(pool.reviews)
    by_platform: dict[str, list[ReviewRecord]] = {}
    for review in deduplicated:
        by_platform.setdefault(review.platform_slug, []).append(review)
    for platform_reviews in by_platform.values():
        platform_reviews.sort(key=lambda r: _sort_key(r.identity_key))

    ordered_platforms = sorted(by_platform)
    queues = [by_platform[slug] for slug in ordered_platforms]
    chosen: list[ReviewRecord] = []
    while len(chosen) < MAX_SELECTED_REVIEWS and any(queues):
        for queue in queues:
            if not queue:
                continue
            chosen.append(queue.pop(0))
            if len(chosen) == MAX_SELECTED_REVIEWS:
                break

    selected: list[SelectedReview] = []
    for review in chosen:
        tokens = count_tokens(review.text)
        truncated = tokens > MAX_REVIEW_TOKENS
        text = truncate_to_token_boundary(review.text) if truncated else review.text
        if truncated:
            tokens = MAX_REVIEW_TOKENS
        selected.append(
            SelectedReview(
                identity_key=review.identity_key,
                platform_slug=review.platform_slug,
                text=text,
                truncated=truncated,
                token_count=tokens,
            )
        )

    return SelectionResult(
        selected=tuple(selected),
        meaningful_pool_count=pool.meaningful_count,
        total_pool_count=len(pool.reviews),
    )
