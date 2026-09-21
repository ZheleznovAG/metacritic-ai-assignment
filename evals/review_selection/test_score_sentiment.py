"""Meta-tests for the `1.1.0` sentiment-coverage scorer: does it catch a skewed selector and accept
a balanced one? Uses the frozen `sentiment_cases.json`, so a scorer that passed everything by
accident would be caught here."""

from __future__ import annotations

import unittest

from baseline_naive import select_reviews as naive_select
from contract import SelectedReview, SelectionPool, SelectionResult, count_tokens
from score_sentiment import bucket, score


def _result(pool: SelectionPool, reviews) -> SelectionResult:
    return SelectionResult(
        selected=tuple(
            SelectedReview(r.identity_key, r.platform_slug, r.text, False, count_tokens(r.text))
            for r in reviews
        ),
        meaningful_pool_count=pool.meaningful_count,
        total_pool_count=len(pool.reviews),
    )


def _balanced_reference(pool: SelectionPool) -> SelectionResult:
    """Deliberately simple reference: three of each side first, then fill in identity order."""
    ordered = sorted(pool.reviews, key=lambda r: r.identity_key)
    chosen: list = []
    for kind in ("negative", "positive"):
        chosen += [r for r in ordered if bucket(r.score, pool.audience) == kind][:3]
    chosen += [r for r in ordered if r not in chosen][: 10 - len(chosen)]
    return _result(pool, chosen[:10])


def _lowest_ids(pool: SelectionPool) -> SelectionResult:
    return _result(pool, sorted(pool.reviews, key=lambda r: r.identity_key)[:10])


class BucketRuleTests(unittest.TestCase):
    def test_scale_depends_on_audience(self) -> None:
        self.assertEqual(bucket(4, "user"), "negative")
        self.assertEqual(bucket(4, "critic"), "negative")
        self.assertEqual(bucket(75, "critic"), "positive")
        self.assertEqual(bucket(7.5, "user"), "positive")
        self.assertEqual(bucket(60, "critic"), "mixed")
        self.assertEqual(bucket(None, "user"), "unscored")


class ScorerDiscriminationTests(unittest.TestCase):
    def test_a_selector_that_ignores_sentiment_fails_on_skewed_pools(self) -> None:
        report = score(_lowest_ids)
        self.assertFalse(report["all_pass"])
        self.assertIn("skew_positive_few_negatives", report["failed"])
        self.assertIn("skew_negative_few_positives", report["failed"])

    def test_the_naive_baseline_is_also_rejected(self) -> None:
        self.assertFalse(score(naive_select)["all_pass"])

    def test_a_balanced_reference_passes_every_case(self) -> None:
        report = score(_balanced_reference)
        self.assertTrue(report["all_pass"], report["failed"])

    def test_every_case_exercises_a_distinct_situation(self) -> None:
        report = score(_balanced_reference)
        self.assertEqual(len({a["case_id"] for a in report["assessments"]}), 7)
        skewed = next(a for a in report["assessments"] if a["case_id"] == "skew_positive_few_negatives")
        self.assertEqual(skewed["available"], {"negative": 4, "positive": 36})


if __name__ == "__main__":
    unittest.main()
