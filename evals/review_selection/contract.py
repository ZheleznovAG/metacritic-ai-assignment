"""REV-EVAL-01 frozen selection interface: pool in, bounded selection out.

A "selector" is any callable `(SelectionPool) -> SelectionResult` satisfying the
contract documented in metric.md. `score_selection.py` evaluates a selector
against `cases.json`; `baseline_naive.py` is one (deliberately naive) example.
This module has no dependency on Django, the real gateway, or any provider —
it is pure data plus the shared token-counting helper, so it can be evaluated
without network access and without IMP-04 existing yet.
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

TOKENIZER_ID = "o200k_harmony"
MAX_SELECTED_REVIEWS = 10
MAX_REVIEW_TOKENS = 450
MAX_GUARDED_PROMPT_TOKENS = 6000
MAX_TOTAL_RESERVATION_TOKENS = 6800

_ENCODING = tiktoken.get_encoding(TOKENIZER_ID)


def count_tokens(text: str) -> int:
    """Untrusted review text: treat token-like substrings as text, never control tokens."""
    return len(_ENCODING.encode(text, disallowed_special=()))


def truncate_to_token_boundary(text: str, max_tokens: int = MAX_REVIEW_TOKENS) -> str:
    """Same mechanics evals/reviews/check_token_budget.py uses: decode the first N tokens."""
    token_ids = _ENCODING.encode(text, disallowed_special=())
    return _ENCODING.decode(token_ids[:max_tokens])


class IncompleteCollectionError(Exception):
    """Raised by a selector when asked to select from a pool that is not `complete`."""


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


def pool_from_case(case: dict) -> SelectionPool:
    reviews = tuple(
        ReviewRecord(
            identity_key=item["identity_key"],
            platform_slug=item["platform_slug"],
            page_offset=item["page_offset"],
            language=item["language"],
            score=item.get("score"),
            text=item["text"],
            meaningful=item["meaningful"],
            duplicate_of=item.get("duplicate_of"),
        )
        for item in case["reviews"]
    )
    return SelectionPool(
        audience=case["audience"],
        game_slug=case["game_slug"],
        collection_status=case["collection_status"],
        reviews=reviews,
    )


def mutate_review_text(pool: SelectionPool, identity_key: str, new_text: str) -> SelectionPool:
    """Return a copy of `pool` with one review's text changed, identity/platform/page/score unchanged.

    Used by the INV-CONTENT-INDEPENDENCE check: the set of *selected identities* must
    not depend on the content of reviews, only on pool membership/completeness.
    """
    reviews = tuple(
        ReviewRecord(
            identity_key=review.identity_key,
            platform_slug=review.platform_slug,
            page_offset=review.page_offset,
            language=review.language,
            score=review.score,
            text=new_text if review.identity_key == identity_key else review.text,
            meaningful=review.meaningful,
            duplicate_of=review.duplicate_of,
        )
        for review in pool.reviews
    )
    return SelectionPool(
        audience=pool.audience,
        game_slug=pool.game_slug,
        collection_status=pool.collection_status,
        reviews=reviews,
    )
