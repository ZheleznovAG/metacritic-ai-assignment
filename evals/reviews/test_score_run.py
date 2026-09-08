"""Offline evidence-integrity regressions for the published SPK-05 baseline."""

import copy
import unittest
from unittest.mock import patch

import score_run


class PublishedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.run_path = score_run.runner.ROOT / "evals/reviews/baseline/run.json"
        self.score_path = self.run_path.with_name("scorecard.json")
        self.run = score_run.load_json(self.run_path)
        self.score = score_run.load_json(self.score_path)

    def verify_changed(self, run=None, score=None):
        original_load = score_run.load_json
        documents = {
            self.run_path: self.run if run is None else run,
            self.score_path: self.score if score is None else score,
        }

        def load(path):
            return copy.deepcopy(documents[path]) if path in documents else original_load(path)

        # In-memory corruption gets past the on-disk hash check so the content
        # validation is exercised independently. No fixture file is rewritten.
        with patch.object(score_run, "load_json", side_effect=load):
            return score_run.verify_scorecard(self.run_path, self.score_path)

    def test_original_is_read_only_and_matches_recorded_score(self):
        with patch.object(score_run.runner, "request_json") as api, patch.object(
            score_run.runner, "atomic_write_json"
        ) as write:
            aggregate = score_run.verify_scorecard(self.run_path, self.score_path)
        self.assertEqual((aggregate["score"], aggregate["maximum"]), (96, 98))
        api.assert_not_called()
        write.assert_not_called()

    def test_dropped_case_cannot_improve_the_average(self):
        self.run["results"].pop(1)
        with self.assertRaisesRegex(ValueError, "every frozen case exactly once"):
            self.verify_changed()

    def test_duplicate_case_cannot_replace_another_case(self):
        self.run["results"][1] = copy.deepcopy(self.run["results"][0])
        with self.assertRaisesRegex(ValueError, "every frozen case exactly once"):
            self.verify_changed()

    def test_saved_pass_flag_does_not_hide_invalid_support(self):
        self.run["results"][0]["output"]["likes"][0]["support"] = ["NOT_IN_INPUT"]
        with self.assertRaisesRegex(ValueError, "structural validation"):
            self.verify_changed()

    def test_critical_score_cannot_be_removed_from_denominator(self):
        self.score["assessments"][0]["scores"]["GROUND"] = "N/A"
        with self.assertRaisesRegex(ValueError, "N/A applicability"):
            self.verify_changed()

    def test_incorrect_aggregate_is_rejected(self):
        self.score["aggregate"]["score"] = 98
        with self.assertRaisesRegex(ValueError, "aggregate"):
            self.verify_changed()

    def test_changed_run_hash_is_rejected(self):
        self.score["run_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "run_sha256"):
            self.verify_changed()


if __name__ == "__main__":
    unittest.main()
