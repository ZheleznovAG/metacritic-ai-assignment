"""Negative controls for the frozen YTP-02 selection scorer (research tooling)."""

from __future__ import annotations

import copy
import unittest

import score_selection as scorer


class ScoreSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.labels = scorer.load("labels.json")
        cls.pool = scorer.load("candidates.json")
        cls.oracle = {game["title"]: game["expected"] for game in cls.labels["games"]}

    def test_expected_choices_pass(self) -> None:
        result = scorer.score(self.oracle, self.labels, self.pool)
        self.assertTrue(result["passed"])
        self.assertEqual(result["accurate"], 20)

    def test_three_misses_still_pass_four_fail(self) -> None:
        choices = dict(self.oracle)
        found = [title for title, video in choices.items() if video]
        for title in found[:3]:
            choices[title] = None
        self.assertTrue(scorer.score(choices, self.labels, self.pool)["passed"])
        choices[found[3]] = None
        self.assertFalse(scorer.score(choices, self.labels, self.pool)["passed"])

    def test_wrong_game_is_a_hard_violation(self) -> None:
        choices = dict(self.oracle, **{"Rogue Racer": "NVHr_-5nzeE"})
        result = scorer.score(choices, self.labels, self.pool)
        self.assertFalse(result["passed"])
        self.assertIn("INV-GAME", result["violations"][0])

    def test_other_language_is_a_hard_violation(self) -> None:
        choices = dict(self.oracle, **{"Pokemon Pokopia": "qaGrShDlH48"})
        result = scorer.score(choices, self.labels, self.pool)
        self.assertFalse(result["passed"])
        self.assertIn("INV-LANGUAGE", result["violations"][0])

    def test_video_outside_pool_is_a_violation(self) -> None:
        choices = dict(self.oracle, **{"Elden Ring": "dQw4w9WgXcQ"})
        result = scorer.score(choices, self.labels, self.pool)
        self.assertIn("INV-POOL", result["violations"][0])

    def test_two_false_positives_fail(self) -> None:
        choices = dict(self.oracle, **{"Sakura: The Eternal Night": "w1IVHqtm9mg"})
        self.assertTrue(scorer.score(choices, self.labels, self.pool)["passed"])
        choices["Kamenkik and Friends"] = "6l4AU155vKw"
        result = scorer.score(choices, self.labels, self.pool)
        self.assertEqual(result["false_positives"], 2)
        self.assertFalse(result["passed"])

    def test_missing_game_is_rejected(self) -> None:
        choices = dict(self.oracle)
        del choices["Elden Ring"]
        with self.assertRaises(ValueError):
            scorer.score(choices, self.labels, self.pool)

    def test_reference_baselines_fail(self) -> None:
        for selector in (scorer.max_views, scorer.ytp01_rule):
            choices = {game["title"]: selector(game) for game in self.pool["games"]}
            self.assertFalse(scorer.score(choices, self.labels, self.pool)["passed"])

    def test_every_expected_video_outranks_no_unlabelled_candidate(self) -> None:
        by_title = {game["title"]: game for game in self.pool["games"]}
        for game in self.labels["games"]:
            if not game["expected"]:
                continue
            views = {
                item["video_id"]: item["views"] or 0
                for item in by_title[game["title"]]["candidates"]
            }
            labelled = {item["video_id"] for item in game["labels"]}
            ahead = {video for video, count in views.items() if count > views[game["expected"]]}
            self.assertLessEqual(ahead, labelled, game["title"])

    def test_labels_are_bound_to_the_candidate_pool(self) -> None:
        import hashlib

        digest = hashlib.sha256((scorer.HERE / "candidates.json").read_bytes()).hexdigest()
        self.assertEqual(self.labels["candidates_sha256"], digest)
        altered = copy.deepcopy(self.labels)
        altered["games"][0]["expected"] = None
        self.assertFalse(scorer.score(self.oracle, altered, self.pool)["rows"][0]["hit"])


if __name__ == "__main__":
    unittest.main()
