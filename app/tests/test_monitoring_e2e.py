"""BON-21 browser checks use actual HTTP/DB state and controlled connection failures."""

import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from django.db import connections
from django.test import LiveServerTestCase, tag
from django.utils import timezone
from playwright.sync_api import Route, expect, sync_playwright
from processing.heartbeat import Heartbeat
from processing.models import ProcessingRun
from processing.monitoring import snapshot


def database_call[T](operation: Callable[[], T]) -> T:
    # Playwright's sync API has an event loop on the caller thread. Keep ORM writes on a
    # separate real connection; do not disable Django's async-safety protection for the test.
    def execute() -> T:
        try:
            return operation()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(execute).result(timeout=10)


@tag("e2e")
class MonitoringBrowserTests(LiveServerTestCase):
    def test_committed_states_freshness_reconnect_and_responsive_ui(self) -> None:
        run = ProcessingRun.objects.create(
            trigger_key="browser-test", scheduled_slot=timezone.now()
        )
        heartbeat = Heartbeat("worker")
        heartbeat.register()
        heartbeat.activity("summary", job_id=23, deadline_seconds=300)
        heartbeat.publish()
        observations: list[dict[str, object]] = []
        errors: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1000})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(self.live_server_url + "/ops/")
                expect(page.locator("#ops-connection")).to_contain_text("Live")
                row = page.locator(f'tr[data-run-id="{run.pk}"]')
                for status in ("queued", "running", "partial", "succeeded", "failed"):
                    database_call(
                        partial(ProcessingRun.objects.filter(pk=run.pk).update, status=status)
                    )
                    committed = time.monotonic()
                    expect(row.locator("td").nth(0)).to_have_text(status, timeout=5000)
                    elapsed = time.monotonic() - committed
                    self.assertLess(elapsed, 5)
                    observations.append(
                        {"status": status, "commit_to_dom_seconds": round(elapsed, 3)}
                    )
                # A missing signal changes process observation, not the recorded run outcome.
                expect(page.locator('[data-role="worker"] .ops__state')).to_have_text(
                    "stale", timeout=5000
                )
                expect(row.locator("td").nth(0)).to_have_text("failed")
                database_call(heartbeat.publish)
                expect(page.locator('[data-role="worker"] .ops__state')).to_have_text(
                    "busy", timeout=5000
                )

                def unavailable(route: Route) -> None:
                    route.abort()

                page.route("**/ops/status/", unavailable)
                expect(page.locator("#ops-connection")).to_contain_text(
                    "data may be stale", timeout=6500
                )
                expect(row.locator("td").nth(0)).to_have_text("failed")
                page.unroute("**/ops/status/", unavailable)
                recovered = time.monotonic()
                expect(page.locator("#ops-connection")).to_contain_text("Live", timeout=5000)
                observations.append({"reconnect_seconds": round(time.monotonic() - recovered, 3)})

                old = database_call(snapshot)
                database_call(
                    lambda: ProcessingRun.objects.filter(pk=run.pk).update(
                        status="succeeded", processed_count=2, selected_count=2
                    )
                )
                expect(row.locator("td").nth(0)).to_have_text("succeeded", timeout=5000)

                def older(route: Route) -> None:
                    route.fulfill(content_type="application/json", body=json.dumps(old))

                page.route("**/ops/status/", older)
                page.locator("#ops-refresh").click()
                expect(page.locator("#ops-connection")).to_contain_text(
                    "data may be stale", timeout=6500
                )
                expect(row.locator("td").nth(0)).to_have_text("succeeded")
                page.unroute("**/ops/status/", older)
                page.locator("#ops-refresh").focus()
                page.keyboard.press("Enter")
                expect(page.locator("#ops-connection")).to_contain_text("Live", timeout=5000)
                page.reload()
                expect(page.locator(f'tr[data-run-id="{run.pk}"] td').nth(0)).to_have_text(
                    "succeeded"
                )

                artifact_dir = os.environ.get("E2E_ARTIFACT_DIR")
                if artifact_dir:
                    folder = Path(artifact_dir)
                    folder.mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(folder / "bon21-monitoring-desktop.png"), full_page=True
                    )
                    (folder / "bon21-browser-timing.json").write_text(
                        json.dumps(observations, indent=2) + "\n", encoding="utf-8"
                    )
                page.set_viewport_size({"width": 390, "height": 844})
                self.assertTrue(
                    page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                )
                if artifact_dir:
                    page.screenshot(
                        path=str(Path(artifact_dir) / "bon21-monitoring-mobile.png"), full_page=True
                    )
                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_server_snapshot_works_without_javascript(self) -> None:
        ProcessingRun.objects.create(
            trigger_key="no-js",
            scheduled_slot=timezone.now(),
            status="partial",
            selected_count=3,
            processed_count=2,
            failed_count=1,
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(java_script_enabled=False)
                page.goto(self.live_server_url + "/ops/")
                self.assertIn(
                    "Refresh now",
                    page.locator("noscript").evaluate("element => element.textContent"),
                )
                expect(page.locator(".ops__table tbody")).to_contain_text("partial")
                page.get_by_role("link", name="Refresh now").click()
                expect(page.locator(".ops__table tbody")).to_contain_text("partial")
            finally:
                browser.close()
