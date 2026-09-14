"""IMP-04 R07/R13/R18: validate actual grounding and the deduplicated input."""

import json
from dataclasses import replace
from typing import Any
from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, TestCase
from reviews import collector
from reviews.models import ReviewCorpus
from summaries import contour, groq_adapter, worker
from summaries.models import ReviewSummary, SummaryAttempt, SummaryClaim, SummaryJob

from tests.test_reviews_collector import FakeClock, FakeGateway, _make_job
from tests.test_reviews_snapshots import NOW, page
from tests.test_summaries_worker import _ok_response
from tests.test_summary_admission import make_job, ok, process


def output() -> dict[str, Any]:
    return {
        "case_id": "job",
        "audience": "critic",
        "status": "ok",
        "likes": [{"claim": "Great combat.", "support": ["R01"]}],
        "dislikes": [],
        "insufficient_data_reason": None,
    }


class OutputTypesTests(SimpleTestCase):
    def test_all_malformed_json_field_types_are_errors_not_exceptions(self) -> None:
        malformed: tuple[object, ...] = (None, True, 7, {}, [1])
        for field in ("case_id", "audience", "status", "likes", "dislikes"):
            for value in malformed:
                with self.subTest(field=field, value=value):
                    value_output = output()
                    value_output[field] = value
                    self.assertTrue(contour.validate_output(value_output, "job", "critic"))

    def test_grounding_requires_a_review_from_this_request(self) -> None:
        value = output()
        for support in ("R10", "R11", "R00", "", "arbitrary"):
            with self.subTest(support=support):
                value["likes"][0]["support"] = [support]
                self.assertTrue(contour.validate_output(value, "job", "critic", {"R01"}))
        value["likes"][0]["support"] = ["R01"]
        self.assertEqual(contour.validate_output(value, "job", "critic", {"R01"}), [])


class SummaryValidationTests(TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(NOW)

    def claim(self) -> SummaryJob:
        claim = worker.claim_next_job(self.clock)
        assert claim is not None
        return claim

    def test_unknown_support_rejects_whole_output_without_partial_claims(self) -> None:
        make_job()
        claim = self.claim()

        def reply(request: httpx.Request) -> httpx.Response:
            response = _ok_response(f"summary-job-{claim.pk}", "critic")
            value = output()
            value["case_id"] = f"summary-job-{claim.pk}"
            value["dislikes"] = [{"claim": "Invented support.", "support": ["R10"]}]
            response["choices"] = [{"message": {"content": json.dumps(value)}}]
            return httpx.Response(200, json=response)

        result = process(claim, self.clock, reply)
        self.assertEqual(result.state, "retryable")
        self.assertFalse(ReviewSummary.objects.exists())
        self.assertFalse(SummaryClaim.objects.exists())
        self.assertEqual(SummaryAttempt.objects.get().error_code, "malformed_output")

    def test_worker_rechecks_grounding_even_if_adapter_mislabels_output_valid(self) -> None:
        make_job()
        claim = self.claim()
        with httpx.Client(transport=httpx.MockTransport(ok)) as client:
            result = groq_adapter.generate_summary(
                client,
                api_key="test-key",
                base_url="https://api.groq.com/openai/v1",
                correlation_id=f"summary-job-{claim.pk}",
                audience="critic",
                reviews=[{"id": "R01", "text": "Combat."}],
            )
        assert result.output is not None
        result.output["likes"][0]["support"] = ["R10"]
        with patch("summaries.worker.groq_adapter.generate_summary", return_value=result):
            saved = process(claim, self.clock, ok)
        self.assertEqual(saved.state, "retryable")
        self.assertFalse(ReviewSummary.objects.exists())

    def test_list_status_finishes_attempt_as_malformed(self) -> None:
        make_job()
        claim = self.claim()

        def reply(request: httpx.Request) -> httpx.Response:
            value = output()
            value["case_id"] = f"summary-job-{claim.pk}"
            value["status"] = []
            return httpx.Response(
                200, json={"choices": [{"message": {"content": json.dumps(value)}}]}
            )

        self.assertEqual(process(claim, self.clock, reply).state, "retryable")
        attempt = SummaryAttempt.objects.get()
        self.assertEqual(attempt.error_code, "malformed_output")
        self.assertIsNotNone(attempt.completed_at)

    def test_three_source_reviews_deduplicated_to_one_use_rule_without_http(self) -> None:
        job = _make_job()
        claim = collector.claim_next_job(self.clock)
        assert claim is not None
        response = page(1, 2, 3)
        response = replace(
            response,
            items=tuple(
                replace(
                    item,
                    text="Identical combat review.",
                    author_or_source_label=None,
                    score_label=None,
                    date_label=None,
                )
                for item in response.items
            ),
        )
        collector.collect_one_page(FakeGateway({None: response}), self.clock, claim)
        corpus = ReviewCorpus.objects.get(game=job.game_platform.game)
        self.assertEqual((corpus.unique_count, corpus.selected_count), (3, 1))
        with patch("summaries.worker.groq_adapter.generate_summary") as call:
            result = process(self.claim(), self.clock, ok)
        call.assert_not_called()
        self.assertEqual(result.state, "insufficient_data")
        self.assertEqual(ReviewSummary.objects.get().method, "rule")
        self.assertFalse(SummaryAttempt.objects.exists())
