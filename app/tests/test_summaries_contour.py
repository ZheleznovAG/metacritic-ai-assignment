from typing import Any

from django.test import SimpleTestCase
from summaries import contour


class ContourFilesArePinnedTests(SimpleTestCase):
    def test_prompt_matches_the_published_frozen_hash(self) -> None:
        actual = contour.sha256_bytes(contour.PROMPT_PATH.read_bytes())
        self.assertEqual(actual, contour.EXPECTED_PROMPT_SHA256)

    def test_schema_matches_the_published_frozen_hash(self) -> None:
        actual = contour.sha256_bytes(contour.SCHEMA_PATH.read_bytes())
        self.assertEqual(actual, contour.EXPECTED_SCHEMA_SHA256)


class RequestPayloadTests(SimpleTestCase):
    def test_payload_carries_the_correlation_id_and_reviews(self) -> None:
        payload = contour.build_request_payload(
            "job-123", "critic", [{"id": "R01", "text": "Great combat."}]
        )
        self.assertEqual(payload["model"], contour.REQUESTED_MODEL)
        user_message = payload["messages"][1]["content"]
        self.assertIn('"case_id":"job-123"', user_message)
        self.assertIn('"audience":"critic"', user_message)
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["seed"], 7)
        self.assertEqual(payload["max_completion_tokens"], 800)

    def test_api_schema_strips_groq_unsupported_keywords(self) -> None:
        payload = contour.build_request_payload("job-1", "user", [])
        schema = payload["response_format"]["json_schema"]["schema"]
        self.assertNotIn("$schema", schema)
        self.assertNotIn("$id", schema)
        claim_schema = schema["$defs"]["claim"]["properties"]["support"]
        self.assertNotIn("minItems", claim_schema)
        self.assertNotIn("maxItems", claim_schema)
        self.assertNotIn("uniqueItems", claim_schema)


class ContourFingerprintTests(SimpleTestCase):
    def test_deterministic_for_the_same_contour(self) -> None:
        self.assertEqual(contour.contour_fingerprint(), contour.contour_fingerprint())

    def test_changes_when_generation_params_change(self) -> None:
        original = contour.contour_fingerprint()
        contour.GENERATION_PARAMS["temperature"] = 0.5
        try:
            changed = contour.contour_fingerprint()
        finally:
            contour.GENERATION_PARAMS["temperature"] = 0
        self.assertNotEqual(original, changed)


class ValidateOutputTests(SimpleTestCase):
    def test_valid_ok_output_passes(self) -> None:
        output = {
            "case_id": "job-1",
            "audience": "critic",
            "status": "ok",
            "likes": [{"claim": "Combat feels great.", "support": ["R01"]}],
            "dislikes": [],
            "insufficient_data_reason": None,
        }
        self.assertEqual(contour.validate_output(output, "job-1", "critic"), [])

    def test_mismatched_correlation_id_fails(self) -> None:
        output: dict[str, Any] = {
            "case_id": "other",
            "audience": "critic",
            "status": "ok",
            "likes": [],
            "dislikes": [],
            "insufficient_data_reason": None,
        }
        errors = contour.validate_output(output, "job-1", "critic")
        self.assertTrue(any("case_id" in e for e in errors))

    def test_insufficient_data_with_claims_fails(self) -> None:
        output = {
            "case_id": "job-1",
            "audience": "user",
            "status": "insufficient_data",
            "likes": [{"claim": "x", "support": ["R01"]}],
            "dislikes": [],
            "insufficient_data_reason": "not_enough_meaningful_reviews",
        }
        errors = contour.validate_output(output, "job-1", "user")
        self.assertTrue(any("empty likes" in e for e in errors))

    def test_too_many_claims_fails(self) -> None:
        output = {
            "case_id": "job-1",
            "audience": "user",
            "status": "ok",
            "likes": [{"claim": f"c{i}", "support": ["R01"]} for i in range(6)],
            "dislikes": [],
            "insufficient_data_reason": None,
        }
        errors = contour.validate_output(output, "job-1", "user")
        self.assertTrue(any("more than five" in e for e in errors))


class NormalizeOutputTests(SimpleTestCase):
    def test_truncates_over_five_items_and_records_the_change(self) -> None:
        output = {
            "likes": [{"claim": f"c{i}", "support": ["R01"]} for i in range(7)],
            "dislikes": [],
        }
        normalized, changes = contour.normalize_output(output)
        self.assertEqual(len(normalized["likes"]), 5)
        self.assertEqual(len(changes), 1)

    def test_never_rewrites_claim_text(self) -> None:
        output = {
            "likes": [{"claim": "exact text", "support": ["R01"]}],
            "dislikes": [],
        }
        normalized, _ = contour.normalize_output(output)
        self.assertEqual(normalized["likes"][0]["claim"], "exact text")
