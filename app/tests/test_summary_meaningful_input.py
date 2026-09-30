"""`MA-01` regression through the real collector, corpus builder, summary worker and card.

The 2026-09-18 audit probe (`research/reviews/20260918_main/probe.py`) showed 20 blank and 3
meaningful reviews reaching the model as one meaningful input out of ten. These tests assert the
corrected behavior with a controlled provider; no live Metacritic or AI request is made.
"""

import json
from dataclasses import replace
from typing import Any

import httpx
from django.test import TestCase
from metacritic.dto import ReviewPageDTO
from presentation.summaries import get_summaries
from reviews import collector
from reviews.models import ReviewCollectionJob, ReviewCorpus
from summaries import contour, worker

from tests.test_reviews_collector import FakeClock, FakeGateway, _item, _make_job
from tests.test_reviews_snapshots import NOW
from tests.test_summary_admission import process

TEXTS = (
    "Combat rewards careful parries and precise timing.",
    "Exploration reveals optional paths with valuable equipment.",
    "Quest markers sometimes point to the wrong location.",
)


class MeaningfulSummaryInputTests(TestCase):
    def _collect(self, meaningful: int) -> tuple[ReviewCollectionJob, FakeClock]:
        job = _make_job("user")
        clock = FakeClock(NOW)
        items = tuple(
            replace(_item(i, source_review_id=f"empty-{i}"), text="") for i in range(20)
        ) + tuple(
            replace(_item(i + 20, source_review_id=f"text-{i}"), text=text)
            for i, text in enumerate(TEXTS[:meaningful])
        )
        claim = collector.claim_next_job(clock)
        assert claim is not None
        collected = collector.collect_one_page(
            FakeGateway({None: ReviewPageDTO(items, len(items), None)}), clock, claim
        )
        self.assertEqual(collected.state, "complete")
        return job, clock

    def test_three_meaningful_reviews_among_twenty_blank_all_reach_the_provider(self) -> None:
        job, clock = self._collect(meaningful=3)
        selected = list(ReviewCorpus.objects.get().items.order_by("ordinal"))
        self.assertEqual(sorted(item.input_text for item in selected), sorted(TEXTS))
        provider_inputs: list[dict[str, Any]] = []

        def provider(request: httpx.Request) -> httpx.Response:
            user = json.loads(json.loads(request.content)["messages"][1]["content"])
            provider_inputs.extend(user["reviews"])
            parry_id = next(r["id"] for r in user["reviews"] if "parries" in r["text"])
            output = {
                "case_id": user["case_id"],
                "audience": user["audience"],
                "status": "ok",
                "likes": [{"claim": "Careful parries and precise timing.", "support": [parry_id]}],
                "dislikes": [],
                "insufficient_data_reason": None,
            }
            return httpx.Response(
                200,
                json={
                    "model": contour.REQUESTED_MODEL,
                    "choices": [
                        {"message": {"content": json.dumps(output)}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                },
            )

        summary_claim = worker.claim_next_job(clock)
        assert summary_claim is not None
        process(summary_claim, clock, provider)

        self.assertEqual(sorted(item["text"] for item in provider_inputs), sorted(TEXTS))
        shown = next(v for v in get_summaries(job.game_platform.game) if v.audience == "user")
        self.assertFalse(shown.insufficient_data)

    def test_two_meaningful_reviews_are_insufficient_without_a_provider_call(self) -> None:
        job, clock = self._collect(meaningful=2)

        def provider(request: httpx.Request) -> httpx.Response:
            raise AssertionError("an insufficient corpus must not reach the provider")

        summary_claim = worker.claim_next_job(clock)
        assert summary_claim is not None
        result = process(summary_claim, clock, provider)

        self.assertEqual(result.state, "insufficient_data")
        shown = next(v for v in get_summaries(job.game_platform.game) if v.audience == "user")
        self.assertTrue(shown.insufficient_data)
