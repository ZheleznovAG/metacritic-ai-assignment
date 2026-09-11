"""The "simple baseline" IMP-04's real candidate selector must be compared against.

Deliberately naive: concatenate reviews in raw fetch order (platform order as given,
pages in ascending offset, no dedup, no interleaving), take the first
MAX_SELECTED_REVIEWS. It does not implement ASM-16's candidate policy (hash-sort
within platform + cross-platform round-robin + cross-platform dedupe) on purpose —
REV-EVAL-01's job is to show this naive approach fails invariants a real candidate
must satisfy, proving the oracle has discriminative power before any candidate exists.
"""

from __future__ import annotations

from contract import (
    MAX_REVIEW_TOKENS,
    MAX_SELECTED_REVIEWS,
    IncompleteCollectionError,
    SelectedReview,
    SelectionPool,
    SelectionResult,
    count_tokens,
    truncate_to_token_boundary,
)


def select_reviews(pool: SelectionPool) -> SelectionResult:
    if pool.collection_status != "complete":
        raise IncompleteCollectionError(
            f"pool for {pool.game_slug}/{pool.audience} is {pool.collection_status!r}, not complete"
        )

    ordered = sorted(pool.reviews, key=lambda review: (review.platform_slug, review.page_offset))
    chosen = ordered[:MAX_SELECTED_REVIEWS]

    selected: list[SelectedReview] = []
    for review in chosen:
        tokens = count_tokens(review.text)
        truncated = tokens > MAX_REVIEW_TOKENS
        text = review.text
        if truncated:
            text = truncate_to_token_boundary(review.text)
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
