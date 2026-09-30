"""Meta-tests for the `1.2.0` meaningful-eligibility scorer: does it catch a selector that spends slots
on blank reviews and accept one that does not? Uses the frozen `meaningful_cases.json`, so a scorer
that passed everything by accident would be caught here."""

from __future__ import annotations

import unittest

from baseline_naive import select_reviews as naive_select
from contract import SelectedReview, SelectionPool, SelectionResult, count_tokens
from score_meaningful import score


def _result(pool: SelectionPool, reviews) -> SelectionResult:
    return SelectionResult(
        selected=tuple(
            SelectedReview(r.identity_key, r.platform_slug, r.text, False, count_tokens(r.text))
            for r in reviews
        ),
        meaningful_pool_count=pool.meaningful_count,
        total_pool_count=len(pool.reviews),
    )


def _lowest_ids(pool: SelectionPool) -> SelectionResult:
    """Blank-blind: `BLANK-*` keys sort before `TEXT-*` keys in every frozen case."""
    return _result(pool, sorted(pool.reviews, key=lambda r: r.identity_key)[:10])


def _meaningful_first(pool: SelectionPool) -> SelectionResult:
    """Deliberately simple reference: meaningful reviews only, in identity order."""
    ordered = sorted(pool.reviews, key=lambda r: r.identity_key)
    return _result(pool, [r for r in ordered if r.meaningful][:10])


class ScorerDiscriminationTests(unittest.TestCase):
    def test_a_blank_blind_selector_fails_the_audit_counterexample(self) -> None:
        report = score(_lowest_ids)
        self.assertFalse(report["all_pass"])
        self.assertIn("audit_blank_flood", report["failed"])
        self.assertNotIn("no_blank_control", report["failed"])
        self.assertNotIn("all_blank", report["failed"])

    def test_the_naive_baseline_is_also_rejected(self) -> None:
        self.assertFalse(score(naive_select)["all_pass"])

    def test_a_meaningful_first_reference_passes_every_case(self) -> None:
        report = score(_meaningful_first)
        self.assertTrue(report["all_pass"], report["failed"])

    def test_every_case_exercises_a_distinct_situation(self) -> None:
        report = score(_meaningful_first)
        self.assertEqual(len({a["case_id"] for a in report["assessments"]}), 7)
        audit = next(a for a in report["assessments"] if a["case_id"] == "audit_blank_flood")
        self.assertEqual((audit["meaningful_available"], audit["meaningful_selected"]), (3, 3))


if __name__ == "__main__":
    unittest.main()
