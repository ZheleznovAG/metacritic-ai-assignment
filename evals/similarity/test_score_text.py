"""Offline checks for the real-catalogue text comparison: metric maths, scorer wiring on a tiny
synthetic snapshot (no model download) and integrity of the committed report."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
import score_text

HERE = Path(__file__).resolve().parent


class BagEmbedder:
    """Hashed bag of words, standing in for the ONNX model."""

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = np.zeros((len(texts), 32), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().split():
                rows[row, int(hashlib.sha256(word.encode()).hexdigest(), 16) % 32] += 1
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return rows / norms


class MetricTests(unittest.TestCase):
    def test_a_perfect_ranking_scores_one_and_an_empty_or_wrong_one_scores_zero(self) -> None:
        judged = {"a": 2, "b": 1, "c": 0}
        self.assertAlmostEqual(score_text.ndcg_at_5(["a", "b"], judged) or 0, 1.0)
        self.assertEqual(score_text.ndcg_at_5([], judged), 0.0)
        self.assertEqual(score_text.ndcg_at_5(["c", "zzz"], judged), 0.0)

    def test_order_matters_and_unlabelled_games_count_as_grade_zero(self) -> None:
        judged = {"a": 2, "b": 1}
        best = score_text.ndcg_at_5(["a", "b"], judged)
        swapped = score_text.ndcg_at_5(["b", "a"], judged)
        padded = score_text.ndcg_at_5(["x", "a", "b"], judged)
        assert best is not None and swapped is not None and padded is not None
        self.assertGreater(best, swapped)
        self.assertGreater(swapped, padded)

    def test_a_query_without_any_positive_grade_is_not_scored(self) -> None:
        self.assertIsNone(score_text.ndcg_at_5(["a"], {"a": 0}))

    def test_only_the_first_five_results_count(self) -> None:
        judged = {"a": 2}
        self.assertEqual(score_text.ndcg_at_5(["1", "2", "3", "4", "5", "a"], judged), 0.0)


class ScoreMethodTests(unittest.TestCase):
    LABELS = {
        "queries": [
            {"source_game_id": "q1", "grades": {"a": {"grade": 2}, "b": {"grade": 1}}},
            {"source_game_id": "q2", "grades": {"c": {"grade": 2}}},
        ]
    }

    def test_means_precision_and_result_counts_are_aggregated_per_method(self) -> None:
        report = score_text.score_method({"q1": ["a", "x"], "q2": ["c"]}, self.LABELS)

        self.assertEqual(report["mean_results_per_query"], 1.5)
        self.assertEqual(report["precision"], round(2 / 3, 3))
        self.assertEqual(report["per_query_ndcg"]["q2"], 1.0)
        self.assertLess(report["per_query_ndcg"]["q1"], 1.0)

    def test_a_missing_ranking_is_an_empty_result_not_a_crash(self) -> None:
        report = score_text.score_method({}, self.LABELS)

        self.assertEqual(report["mean_ndcg_at_5"], 0.0)
        self.assertIsNone(report["precision"])


class RankAllTests(unittest.TestCase):
    def test_both_methods_are_ranked_for_labelled_queries_from_a_snapshot(self) -> None:
        snapshot = [
            {
                "source_game_id": f"g{i}",
                "title": f"Game {i}",
                "genres": ["Puzzle"] if i % 2 else ["Racing"],
                "description": ("dragon castle knight quest " if i % 2 else "car track lap engine ")
                * 6
                + f"extra{i}",
            }
            for i in range(1, 41)
        ]
        original = score_text.load_labels
        score_text.load_labels = lambda: {"queries": [{"source_game_id": "g1", "grades": {}}]}  # type: ignore[assignment]
        try:
            rankings = score_text.rank_all(snapshot, BagEmbedder())
        finally:
            score_text.load_labels = original  # type: ignore[assignment]

        self.assertEqual(set(rankings), {"genre-jaccard", "text-hybrid"})
        self.assertTrue(rankings["genre-jaccard"]["g1"])
        self.assertTrue(all(int(g[1:]) % 2 == 1 for g in rankings["text-hybrid"]["g1"]))


class CommittedReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = json.loads((HERE / "text_report.json").read_text(encoding="utf-8"))
        self.labels = json.loads((HERE / "text_labels.json").read_text(encoding="utf-8"))

    def test_the_report_was_made_from_the_committed_labels(self) -> None:
        digest = hashlib.sha256((HERE / "text_labels.json").read_bytes()).hexdigest()
        self.assertEqual(self.report["labels_sha256"], digest)

    def test_the_report_covers_every_labelled_query_for_both_methods(self) -> None:
        queries = {q["source_game_id"] for q in self.labels["queries"]}
        for method in ("genre-jaccard", "text-hybrid"):
            self.assertEqual(set(self.report["methods"][method]["per_query_ndcg"]), queries)

    def test_the_selected_method_beats_the_previous_one_by_a_wide_margin(self) -> None:
        old = self.report["methods"]["genre-jaccard"]["mean_ndcg_at_5"]
        new = self.report["methods"]["text-hybrid"]["mean_ndcg_at_5"]
        self.assertGreater(new, old + 0.3)

    def test_labels_are_well_formed(self) -> None:
        for query in self.labels["queries"]:
            self.assertIn(
                query["source_game_id"], {q["source_game_id"] for q in self.labels["queries"]}
            )
            for entry in query["grades"].values():
                self.assertIn(entry["grade"], (0, 1, 2))
            self.assertNotIn(query["source_game_id"], query["grades"])


if __name__ == "__main__":
    unittest.main()
