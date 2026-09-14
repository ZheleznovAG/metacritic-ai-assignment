"""Independent oracle checks and negative controls; no production ranking method."""

from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import score_similarity as scorer


class SimilarityOracleTests(unittest.TestCase):
    def setUp(self):
        self.document = scorer.load_cases()
        self.answers = {}
        for case in self.document["cases"]:
            judged = sorted(case["judgments"], key=lambda item: (-item["grade"], item["game_id"]))
            self.answers[case["query_id"]] = [item["game_id"] for item in judged if item["grade"] > 0][:5]

    def reference(self, query, catalog):
        # Deliberately reads labels in this test double. Never imported by a real ranker.
        return self.answers[query].copy()

    def broken_first(self, output):
        def rank(query, catalog):
            return output if query == 101 else self.reference(query, catalog)
        return scorer.evaluate(self.document, rank)

    def test_reference_checks_all_cases_without_choosing_a_method(self):
        result = scorer.evaluate(self.document, self.reference)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["positive_case_count"], 9)
        self.assertEqual(result["empty_or_negative_case_count"], 5)
        self.assertEqual(result["macro_ndcg_at_5"], 1.0)

    def test_dcg_and_ranking_penalty_match_hand_calculation(self):
        ideal = 3 + 1 / math.log2(3)
        self.assertAlmostEqual(scorer.dcg([2, 1]), ideal)
        self.assertAlmostEqual(scorer.ndcg([2, 1], {1: 2, 2: 1}),
                               (1 + 3 / math.log2(3)) / ideal)
        self.assertAlmostEqual(scorer.ndcg([1], {1: 2, 2: 1}), 3 / ideal)
        self.assertIsNone(scorer.ndcg([], {2: 0}))

    def test_empty_output_cannot_pass_by_satisfying_only_exclusions(self):
        result = scorer.evaluate(self.document, lambda query, catalog: [])
        self.assertTrue(result["hard_invariants_pass"])
        self.assertFalse(result["quality_pass"])
        self.assertEqual(result["macro_ndcg_at_5"], 0.0)

    def test_case_floor_rejects_failure_even_when_macro_passes(self):
        # One of nine positive cases can be mostly omitted while the average stays above .90.
        result = self.broken_first([102])
        self.assertGreater(result["macro_ndcg_at_5"], 0.90)
        self.assertLess(result["min_case_ndcg_at_5"], 0.80)
        self.assertFalse(result["accepted"])

    def test_each_structural_counterexample_is_rejected(self):
        outputs = {
            "INV-CAP": [101, 102, 103, 104, 107, 109],
            "INV-SAVED": [999999],
            "INV-NO-SELF": [101],
            "INV-UNIQUE": [102, 102],
            "INV-NONMATCH": [107],
            "INV-VALID-RESULT": [True],
        }
        for invariant, output in outputs.items():
            with self.subTest(invariant=invariant):
                result = self.broken_first(output)
                self.assertFalse(result["accepted"])
                self.assertFalse(result["cases"][0]["hard_invariants"][invariant])

    def test_duplicate_and_unknown_ids_cannot_earn_extra_gain(self):
        self.assertEqual(scorer.ndcg([1, 1, 1, 1, 1], {1: 2}), 1.0)
        self.assertEqual(scorer.ndcg([999], {1: 2}), 0.0)

    def test_nondeterministic_repeat_is_rejected(self):
        counter = 0
        def alternating(query, catalog):
            nonlocal counter
            counter += 1
            result = self.reference(query, catalog)
            return list(reversed(result)) if counter % 2 else result
        result = scorer.evaluate(self.document, alternating)
        self.assertFalse(result["cases"][0]["hard_invariants"]["INV-DETERMINISTIC"])
        self.assertFalse(result["accepted"])

    def test_input_order_dependency_is_rejected_even_with_relevant_results(self):
        def input_order(query, catalog):
            relevant = set(self.answers[query])
            return [game.id for game in catalog if game.id in relevant]
        result = scorer.evaluate(self.document, input_order)
        self.assertFalse(result["cases"][0]["hard_invariants"]["INV-DETERMINISTIC"])

    def test_checks_apply_to_later_calls_too(self):
        def late_bad_result(query, catalog):
            if query == 101 and catalog[-1].id == query:
                return [107]
            return self.reference(query, catalog)
        result = scorer.evaluate(self.document, late_bad_result)
        self.assertFalse(result["cases"][0]["hard_invariants"]["INV-NONMATCH"])
        self.assertFalse(result["accepted"])

    def test_unknown_query_must_not_return_a_saved_neighbor(self):
        def missing_query(query, catalog):
            return [1402] if query == 1401 else self.reference(query, catalog)
        result = scorer.evaluate(self.document, missing_query)
        self.assertFalse(result["cases"][-1]["hard_invariants"]["INV-QUERY"])
        self.assertFalse(result["accepted"])

    def test_catalog_mutation_is_an_explicit_failure(self):
        def mutating(query, catalog):
            if catalog:
                catalog[0].title = "modified"
            return []
        result = scorer.evaluate(self.document, mutating)
        self.assertFalse(result["accepted"])
        self.assertIn("FrozenInstanceError", result["cases"][0]["errors"])

    def test_malformed_result_and_exception_do_not_escape_evaluator(self):
        for value in (None, "102", [None], [[102]], {"id": 102}):
            with self.subTest(value=value):
                self.assertFalse(self.broken_first(value)["accepted"])
        def raises(query, catalog):
            raise RuntimeError("counterexample")
        self.assertFalse(scorer.evaluate(self.document, raises)["accepted"])

    def test_judgment_coverage_and_identity_are_validated(self):
        for mutation in ("unjudged", "duplicate_game", "duplicate_case", "invalid_grade"):
            document = deepcopy(self.document)
            if mutation == "unjudged":
                document["cases"][0]["judgments"].pop()
            elif mutation == "duplicate_game":
                document["cases"][0]["catalog"].append(document["cases"][0]["catalog"][0])
            elif mutation == "duplicate_case":
                document["cases"].append(document["cases"][0])
            else:
                document["cases"][0]["judgments"][0]["grade"] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                scorer.validate_cases(document)

    def test_frozen_manifest_rejects_any_dataset_byte_change(self):
        scorer.verify_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (*scorer.FROZEN_FILES, "manifest.json"):
                (root / name).write_bytes((scorer.ROOT / name).read_bytes())
            (root / "cases.json").write_bytes((root / "cases.json").read_bytes() + b"\n")
            with patch.object(scorer, "ROOT", root), self.assertRaisesRegex(ValueError, "Frozen oracle drift"):
                scorer.verify_manifest()


if __name__ == "__main__":
    unittest.main()
