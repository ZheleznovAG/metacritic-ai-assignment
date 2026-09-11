"""Meta-tests for the REV-EVAL-01 scorer itself: does it actually catch a bad selector?

These do not touch cases.json; they use tiny synthetic pools so a broken invariant
check would be caught even if every frozen case happened to pass by accident.
"""

from __future__ import annotations

import unittest

from contract import (
    IncompleteCollectionError,
    SelectedReview,
    SelectionPool,
    SelectionResult,
    count_tokens,
)
from score_selection import score_case


def _selected(reviews) -> tuple[SelectedReview, ...]:
    return tuple(
        SelectedReview(
            identity_key=r.identity_key,
            platform_slug=r.platform_slug,
            text=r.text,
            truncated=False,
            token_count=count_tokens(r.text),
        )
        for r in reviews
    )


def _pool(reviews, *, collection_status: str = "complete", audience: str = "user") -> dict:
    return {
        "id": "synthetic",
        "audience": audience,
        "game_slug": "synthetic-game",
        "collection_status": collection_status,
        "reviews": reviews,
    }


def _review(key: str, *, page_offset: int = 0, platform: str = "pc", meaningful: bool = True, duplicate_of=None, text: str = "Some review text."):
    return {
        "identity_key": key,
        "platform_slug": platform,
        "page_offset": page_offset,
        "language": "en",
        "score": 7,
        "meaningful": meaningful,
        "duplicate_of": duplicate_of,
        "text": text,
    }


class SelectAll(object):
    """Selects every review, in pool order, ignoring the cap. Should fail INV-CAP."""

    def __call__(self, pool: SelectionPool) -> SelectionResult:
        return SelectionResult(
            selected=_selected(pool.reviews),
            meaningful_pool_count=pool.meaningful_count,
            total_pool_count=len(pool.reviews),
        )


class IgnoresCollectionStatus(object):
    """Never checks collection_status. Should fail INV-COMPLETE."""

    def __call__(self, pool: SelectionPool) -> SelectionResult:
        return SelectionResult(
            selected=_selected(pool.reviews[:10]),
            meaningful_pool_count=pool.meaningful_count,
            total_pool_count=len(pool.reviews),
        )


class SelectsBothDuplicates(object):
    """Ignores duplicate_of grouping. Should fail INV-DEDUP."""

    def __call__(self, pool: SelectionPool) -> SelectionResult:
        return SelectionResult(
            selected=_selected(pool.reviews[:10]),
            meaningful_pool_count=pool.meaningful_count,
            total_pool_count=len(pool.reviews),
        )


class ContentDependentOrder(object):
    """Orders by text LENGTH, so appending text to one review can flip which items land
    in the top 10 by pushing it (or another item) across the cutoff. Should fail
    INV-CONTENT-INDEPENDENCE: a correct selector's chosen identity set must depend only
    on pool membership/completeness, never on review content."""

    def __call__(self, pool: SelectionPool) -> SelectionResult:
        ordered = sorted(pool.reviews, key=lambda r: (len(r.text), r.identity_key))[:10]
        return SelectionResult(
            selected=_selected(ordered),
            meaningful_pool_count=pool.meaningful_count,
            total_pool_count=len(pool.reviews),
        )


class FabricatesAReview(object):
    """Returns an identity_key not present in the pool. Should fail INV-NO-FABRICATION."""

    def __call__(self, pool: SelectionPool) -> SelectionResult:
        selected = (
            SelectedReview(
                identity_key="NOT-IN-POOL",
                platform_slug="pc",
                text="invented",
                truncated=False,
                token_count=count_tokens("invented"),
            ),
        )
        return SelectionResult(selected=selected, meaningful_pool_count=pool.meaningful_count, total_pool_count=len(pool.reviews))


class LiesAboutMeaningfulCount(object):
    """Reports a fixed meaningful count regardless of the pool. Should fail INV-MEANINGFUL-COUNT."""

    def __call__(self, pool: SelectionPool) -> SelectionResult:
        return SelectionResult(
            selected=_selected(pool.reviews[:10]),
            meaningful_pool_count=999,
            total_pool_count=len(pool.reviews),
        )


class CorrectSmallSelector(object):
    """A hand-written correct selector for a small pool, used as a positive control."""

    def __call__(self, pool: SelectionPool) -> SelectionResult:
        if pool.collection_status != "complete":
            raise IncompleteCollectionError("not complete")
        canonical_seen: set[str] = set()
        chosen = []
        for review in sorted(pool.reviews, key=lambda r: r.identity_key):
            group = review.duplicate_of or review.identity_key
            if group in canonical_seen:
                continue
            canonical_seen.add(group)
            chosen.append(review)
        chosen = chosen[:10]
        return SelectionResult(
            selected=_selected(chosen),
            meaningful_pool_count=pool.meaningful_count,
            total_pool_count=len(pool.reviews),
        )


class ScorerCatchesBadSelectorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.big_pool_reviews = [_review(f"K{i}") for i in range(15)]

    def test_select_all_fails_cap(self) -> None:
        case = _pool(self.big_pool_reviews)
        result = score_case(case, SelectAll())
        self.assertEqual(result["invariants"]["INV-CAP"], "fail")

    def test_ignoring_incomplete_collection_fails_complete_invariant(self) -> None:
        case = _pool([_review("K1")], collection_status="partial")
        result = score_case(case, IgnoresCollectionStatus())
        self.assertEqual(result["invariants"]["INV-COMPLETE"], "fail")

    def test_selecting_both_duplicates_fails_dedup(self) -> None:
        reviews = [_review("K1"), _review("K2", duplicate_of="K1")]
        case = _pool(reviews)
        result = score_case(case, SelectsBothDuplicates())
        self.assertEqual(result["invariants"]["INV-DEDUP"], "fail")

    def test_content_dependent_ordering_fails_content_independence(self) -> None:
        reviews = [_review(f"K{i}", text=f"text-{i:02d}") for i in range(15)]
        case = _pool(reviews)
        result = score_case(case, ContentDependentOrder())
        self.assertEqual(result["invariants"]["INV-CONTENT-INDEPENDENCE"], "fail")

    def test_fabricated_review_fails_no_fabrication(self) -> None:
        case = _pool([_review("K1")])
        result = score_case(case, FabricatesAReview())
        self.assertEqual(result["invariants"]["INV-NO-FABRICATION"], "fail")

    def test_wrong_meaningful_count_fails(self) -> None:
        case = _pool([_review("K1", meaningful=False), _review("K2")])
        result = score_case(case, LiesAboutMeaningfulCount())
        self.assertEqual(result["invariants"]["INV-MEANINGFUL-COUNT"], "fail")

    def test_must_include_at_least_one_of_fails_when_absent(self) -> None:
        case = _pool([_review(f"K{i}") for i in range(12)])
        case["must_include_at_least_one_of"] = ["NEVER-SELECTED"]
        result = score_case(case, CorrectSmallSelector())
        self.assertEqual(result["invariants"]["INV-PAGE-COVERAGE"], "fail")

    def test_correct_selector_passes_everything_applicable(self) -> None:
        reviews = [_review("K1"), _review("K2", duplicate_of="K1"), _review("K3", meaningful=False)]
        case = _pool(reviews)
        result = score_case(case, CorrectSmallSelector())
        applicable = {k: v for k, v in result["invariants"].items() if v != "n/a"}
        self.assertTrue(applicable, "expected at least one applicable invariant")
        self.assertTrue(all(status == "pass" for status in applicable.values()), applicable)

    def test_incomplete_pool_marks_every_other_invariant_not_applicable(self) -> None:
        case = _pool([_review("K1")], collection_status="partial")
        result = score_case(case, CorrectSmallSelector())
        self.assertEqual(result["invariants"]["INV-COMPLETE"], "pass")
        for name, status in result["invariants"].items():
            if name != "INV-COMPLETE":
                self.assertEqual(status, "n/a", name)


if __name__ == "__main__":
    unittest.main()
