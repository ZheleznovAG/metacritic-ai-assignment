"""Dated adversarial audit probes, not application acceptance tests or CI gates.

Run only with the checks role/database. Assertions reproduce the reviewed defects;
correcting those defects should make these historical assertions fail.
No live Metacritic or AI requests are made.
"""

import json
import os
from pathlib import Path
import sys
import unittest
from dataclasses import replace

ROOT = Path(os.environ.get("AUDIT_SOURCE_ROOT", Path.cwd()))
sys.path.insert(0, str(ROOT / "app"))
if os.environ.get("APP_ENV") != "test" or not os.environ.get("POSTGRES_DB", "").endswith("_checks"):
    raise SystemExit("Use the disposable checks environment")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

import httpx
from bs4 import BeautifulSoup
from django.core.management import call_command
from django.test import TestCase
from django.test.runner import DiscoverRunner
from metacritic.dto import ReviewPageDTO
from metacritic.parser import _extract_nuxt_payload, _find_game_record, parse_game_detail
from presentation.summaries import get_summaries
from reviews import collector
from reviews.models import ReviewCorpus
from reviews.snapshots import collection_state
from summaries import contour, worker
from tests.test_reviews_collector import FakeClock, FakeGateway, _item, _make_job
from tests.test_reviews_snapshots import NOW
from tests.test_summary_admission import process

OBSERVATIONS = {}


class MainAuditProbes(TestCase):
    def test_blank_records_displace_three_substantive_reviews(self):
        initial = _make_job("user")
        clock = FakeClock(NOW)
        texts = (
            "Combat rewards careful parries and precise timing.",
            "Exploration reveals optional paths with valuable equipment.",
            "Quest markers sometimes point to the wrong location.",
        )
        items = tuple(
            replace(_item(i, source_review_id=f"empty-{i}"), text="") for i in range(20)
        ) + tuple(
            replace(_item(i + 20, source_review_id=f"text-{i}"), text=text)
            for i, text in enumerate(texts)
        )
        claim = collector.claim_next_job(clock)
        collected = collector.collect_one_page(
            FakeGateway({None: ReviewPageDTO(items, len(items), None)}), clock, claim
        )
        self.assertEqual(collected.state, "complete")
        corpus = ReviewCorpus.objects.get()
        selected = list(corpus.items.order_by("ordinal"))
        self.assertEqual(len(selected), 10)
        self.assertEqual(sum(bool(item.input_text.strip()) for item in selected), 1)
        provider_inputs = []

        def provider(request):
            payload = json.loads(request.content)
            user = json.loads(payload["messages"][1]["content"])
            provider_inputs.extend(user["reviews"])
            # A controlled provider obeying the frozen prompt's minimum-three rule.
            # This demonstrates request loss, not a measured live-model response.
            output = {
                "case_id": user["case_id"],
                "audience": user["audience"],
                "status": "insufficient_data",
                "likes": [],
                "dislikes": [],
                "insufficient_data_reason": "not_enough_meaningful_reviews",
            }
            return httpx.Response(200, json={
                "model": contour.REQUESTED_MODEL,
                "choices": [{"message": {"content": json.dumps(output)}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            })

        summary_claim = worker.claim_next_job(clock)
        result = process(summary_claim, clock, provider)
        self.assertEqual(result.state, "insufficient_data")
        shown = next(view for view in get_summaries(initial.game_platform.game) if view.audience == "user")
        self.assertTrue(shown.insufficient_data)
        OBSERVATIONS["MA-01"] = {
            "collected": collected.fetched_count,
            "substantive_reviews_in_complete_source": 3,
            "selected": len(selected),
            "selected_nonempty": sum(bool(item.input_text.strip()) for item in selected),
            "provider_requests": 1,
            "provider_nonempty_inputs": sum(bool(item["text"].strip()) for item in provider_inputs),
            "summary_state_with_prompt_compliant_fake": result.state,
            "ui_state": shown.state,
        }

    def test_corrupt_platform_reference_is_silently_omitted(self):
        original_html = (ROOT / "app/tests/fixtures/metacritic/elden_ring_detail.min.html").read_text(encoding="utf-8")
        url = "https://www.metacritic.com/game/elden-ring/"
        original = parse_game_detail(original_html, url)
        soup = BeautifulSoup(original_html, "html.parser")
        payload = _extract_nuxt_payload(soup)
        record = _find_game_record(payload, "elden-ring")
        payload[record["platforms"]][-1] = len(payload) + 100
        soup.find("script", id="__NUXT_DATA__").string = json.dumps(payload)
        parsed = parse_game_detail(str(soup), url)
        self.assertEqual(len(original.platforms), 5)
        self.assertEqual(len(parsed.platforms), 4)
        OBSERVATIONS["MA-02"] = {
            "original_platforms": len(original.platforms),
            "corrupted_platform_reference_count": 1,
            "returned_platforms": len(parsed.platforms),
            "parser_rejected": False,
        }

    def test_first_collection_failure_is_rendered_as_pending(self):
        job = _make_job("user")
        job.state = "unstable"
        job.last_error = "total_results_changed"
        job.save(update_fields=["state", "last_error"])
        game = job.game_platform.game
        collection = collection_state(game, "user")
        shown = next(view for view in get_summaries(game) if view.audience == "user")
        response = self.client.get(f"/games/{game.pk}/")
        self.assertEqual(collection.reason, "collection_unstable")
        self.assertEqual(shown.state, "pending")
        self.assertIsNone(shown.stale_reason)
        self.assertContains(response, "Pending — review collection or summarisation has not completed yet.")
        self.assertNotContains(response, "The source changed during review collection.")
        OBSERVATIONS["MA-03"] = {
            "collection_state": job.state,
            "collection_reason": collection.reason,
            "existing_summary": False,
            "ui_state": shown.state,
            "ui_reason": shown.stale_reason,
            "http_status": response.status_code,
        }


if __name__ == "__main__":
    call_command("collectstatic", verbosity=0, interactive=False)
    runner = DiscoverRunner(verbosity=1, interactive=False)
    runner.setup_test_environment()
    old_config = runner.setup_databases()
    try:
        result = runner.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(MainAuditProbes))
    finally:
        runner.teardown_databases(old_config)
        runner.teardown_test_environment()
    print(json.dumps({"reviewed_head": "4109ef17b624afbe977dae33dd13a0ecfdb3836e", "observations": OBSERVATIONS}, indent=2))
    raise SystemExit(not result.wasSuccessful())
