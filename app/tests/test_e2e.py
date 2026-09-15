"""IMP-07 / G4: one actual processing-to-browser journey, no live external services."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
from catalog.models import Game
from django.test import LiveServerTestCase, tag
from playwright.sync_api import Browser, Route, expect, sync_playwright
from processing.models import DailyCandidate
from processing.scheduler import run_tick
from reviews import collector
from reviews.models import ReviewCollectionJob
from summaries import contour, worker
from summaries.models import ReviewSummary, SummaryAttempt

from tests.e2e_scenario import (
    COVER_URL,
    CRITIC_DISLIKE,
    CRITIC_LIKE,
    LIKES_BY_AUDIENCE,
    TRAILER_URL,
    USER_DISLIKE,
    USER_LIKE,
    ScenarioGateway,
)
from tests.test_reviews_collector import FakeClock
from tests.test_summaries_worker import _ok_response
from tests.test_summary_admission import process


@tag("e2e")
class MandatoryJourneyTests(LiveServerTestCase):
    def test_processing_search_filter_sort_summaries_and_similar_navigation(self) -> None:
        clock = FakeClock(datetime(2026, 9, 15, 10, tzinfo=UTC))
        gateway = ScenarioGateway()
        provider_audiences: list[str] = []

        def provider(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            user = json.loads(payload["messages"][1]["content"])
            audience = user["audience"]
            provider_audiences.append(audience)
            like, dislike = LIKES_BY_AUDIENCE[audience]
            self.assertEqual(len(user["reviews"]), 3)
            self.assertIn(like, user["reviews"][0]["text"])
            response = _ok_response(
                user["case_id"],
                audience,
                likes=[{"claim": like, "support": ["R01"]}],
                dislikes=[{"claim": dislike, "support": ["R01"]}],
            )
            return httpx.Response(200, json=response)

        with patch("httpx.HTTPTransport.handle_request", side_effect=AssertionError("Live HTTP")):
            self.assertEqual(Game.objects.count(), 0)
            tick = run_tick(gateway, clock)
            self.assertEqual((tick.outcome, tick.run.processed_count), ("succeeded", 4))
            self.assertEqual(DailyCandidate.objects.filter(state="processed").count(), 4)
            self.assertEqual(run_tick(gateway, clock).outcome, "skipped_duplicate")
            for _ in range(20):
                claim = collector.claim_next_job(clock)
                if claim is None:
                    break
                self.assertIn(
                    collector.collect_one_page(gateway, clock, claim).state,
                    ("pending", "complete", "empty"),
                )
            else:
                self.fail("Collection did not terminate")
            self.assertEqual(
                ReviewCollectionJob.objects.exclude(state__in=("complete", "empty")).count(), 0
            )
            self.assertEqual(len(gateway.review_calls), 12)
            for _ in range(12):
                summary_job = worker.claim_next_job(clock)
                if summary_job is None:
                    break
                self.assertIn(
                    process(summary_job, clock, provider).state, ("succeeded", "insufficient_data")
                )
                clock.instant += timedelta(minutes=2)
            else:
                self.fail("Summary queue did not terminate")

        self.assertCountEqual(provider_audiences, ["critic", "user"])
        self.assertEqual(SummaryAttempt.objects.count(), 2)
        anchor = Game.objects.get(source_game_id="e2e-anchor")
        peer = Game.objects.get(source_game_id="e2e-peer")
        self.assertEqual(ReviewSummary.objects.filter(job__game=anchor).count(), 2)

        unexpected_requests: list[str] = []
        screenshot_dir = os.environ.get("E2E_ARTIFACT_DIR")
        if screenshot_dir:
            Path(screenshot_dir).mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                self._run_browser_journey(
                    browser, screenshot_dir, unexpected_requests, anchor, peer
                )
            finally:
                browser.close()

    def _run_browser_journey(
        self,
        browser: Browser,
        screenshot_dir: str | None,
        unexpected_requests: list[str],
        anchor: Game,
        peer: Game,
    ) -> None:
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request_route: Route) -> None:
            url = request_route.request.url
            if url.startswith(self.live_server_url + "/"):
                request_route.continue_()
            elif url == COVER_URL:
                request_route.fulfill(
                    content_type="image/svg+xml",
                    body='<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
                    '<rect width="400" height="300" fill="#476782"/></svg>',
                )
            else:
                unexpected_requests.append(url)
                request_route.abort()

        page.route("**/*", route)
        page.goto(self.live_server_url)
        expect(page.locator(".game-list__title")).to_have_text(
            ["Alpha Quest", "BETA Quest", "Orbit Puzzler", "Unscored Quest"]
        )
        page.locator("#q").fill("qUeSt")
        page.get_by_role("button", name="Filter", exact=True).click()
        expect(page.locator(".game-list__title")).to_have_text(
            ["Alpha Quest", "BETA Quest", "Unscored Quest"]
        )
        page.locator("#platform").select_option("pc")
        page.get_by_role("button", name="Filter", exact=True).click()
        expect(page.locator(".game-list__title")).to_have_text(
            ["BETA Quest", "Alpha Quest", "Unscored Quest"]
        )
        expect(page.locator(".game-list__score")).to_have_text(["80", "70", "No score"])
        selected_query = urlsplit(page.url).query
        if screenshot_dir:
            page.screenshot(
                path=str(Path(screenshot_dir) / "imp-07-fixture-list.png"), full_page=True
            )
        page.get_by_role("link").filter(has=page.get_by_text("Alpha Quest", exact=True)).click()
        expect(page.locator("h1")).to_have_text("Alpha Quest")
        self.assertEqual(urlsplit(page.url).path, f"/games/{anchor.id}/")
        expect(page.locator(".game-card__facts")).to_contain_text("Example Studio")
        expect(page.locator(".game-card__facts")).to_contain_text(
            "A synthetic adventure with responsive combat and rewarding exploration."
        )
        expect(page.get_by_role("link", name="Watch trailer")).to_have_attribute(
            "href", TRAILER_URL
        )
        expect(page.locator(".game-card__cover")).to_have_js_property("complete", True)
        self.assertGreater(page.locator(".game-card__cover").evaluate("e => e.naturalWidth"), 0)
        platform_rows = page.locator(".game-card__platforms tbody tr")
        expect(platform_rows).to_have_count(2)
        expect(platform_rows.nth(0)).to_contain_text("70")
        expect(platform_rows.nth(1)).to_contain_text("95")
        for row in platform_rows.all():
            expect(row).to_contain_text("8.1")
        critics = page.locator(".game-card__summary").filter(
            has=page.get_by_role("heading", name="Critics", exact=True)
        )
        users = page.locator(".game-card__summary").filter(
            has=page.get_by_role("heading", name="Users", exact=True)
        )
        for claim_text in (CRITIC_LIKE, CRITIC_DISLIKE):
            expect(critics).to_contain_text(claim_text)
        for claim_text in (USER_LIKE, USER_DISLIKE):
            expect(users).to_contain_text(claim_text)
        expect(critics).not_to_contain_text(USER_LIKE)
        expect(users).not_to_contain_text(CRITIC_LIKE)
        provenance = page.locator(".summary-provenance")
        expect(provenance).to_have_count(2)
        expect(provenance.first).to_contain_text(contour.REQUESTED_MODEL)
        expect(page.get_by_text("Pending —", exact=False)).to_have_count(0)
        expect(page.locator(".summary-stale")).to_have_count(0)
        for entry in provenance.all():
            expect(entry).to_contain_text("3 of 3 fetched")
        self.assertTrue(
            page.locator("main").evaluate("e => getComputedStyle(e).maxWidth !== 'none'")
        )
        if screenshot_dir:
            page.screenshot(
                path=str(Path(screenshot_dir) / "imp-07-fixture-card.png"), full_page=True
            )
        page.set_viewport_size({"width": 390, "height": 844})
        self.assertTrue(page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
        if screenshot_dir:
            page.screenshot(
                path=str(Path(screenshot_dir) / "imp-07-fixture-mobile.png"), full_page=True
            )
        page.locator(".similar-games a").click()
        expect(page.locator("h1")).to_have_text("BETA Quest")
        self.assertEqual(urlsplit(page.url).path, f"/games/{peer.id}/")
        self.assertEqual(urlsplit(page.url).query, selected_query)
        page.get_by_role("link", name="Back to results", exact=False).click()
        expect(page.locator("#q")).to_have_value("qUeSt")
        expect(page.locator("#platform")).to_have_value("pc")
        expect(page.locator(".game-list__title")).to_have_text(
            ["BETA Quest", "Alpha Quest", "Unscored Quest"]
        )
        page.locator("#q").fill("no-such-title")
        page.get_by_role("button", name="Filter", exact=True).click()
        expect(page.locator(".game-list__empty")).to_be_visible()
        page.get_by_role("link", name="Reset", exact=True).click()
        expect(page.locator(".game-list__title")).to_have_count(4)
        self.assertEqual(unexpected_requests, [])
        self.assertEqual(errors, [])
