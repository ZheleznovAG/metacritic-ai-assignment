"""BON-22 browser checks: anonymous/permission-gated visibility, real login, a real admitted
manual-run POST, and the dispatcher's claim simulated the same way `test_monitoring_e2e.py`
simulates background work -- direct DB/service calls on a separate connection, not a live
`run_scheduler` process."""

import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import connections
from django.test import LiveServerTestCase, tag
from playwright.sync_api import expect, sync_playwright
from processing.clock import SystemClock
from processing.models import ManualRunRequest, TriggerAdmission
from processing.scheduler import run_manual

from tests.test_processing_scheduler import FakeGateway, _identity


def database_call[T](operation: Callable[[], T]) -> T:
    def execute() -> T:
        try:
            return operation()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(execute).result(timeout=10)


def _make_operator(username: str, password: str, *, can_trigger: bool) -> User:
    user = User.objects.create_user(username=username, password=password)
    if can_trigger:
        content_type = ContentType.objects.get_for_model(ManualRunRequest)
        permission = Permission.objects.get(content_type=content_type, codename="trigger_run")
        user.user_permissions.add(permission)
    return user


@tag("e2e")
class OperatorBrowserTests(LiveServerTestCase):
    def test_anonymous_login_permission_and_a_real_admitted_manual_run(self) -> None:
        database_call(lambda: TriggerAdmission.objects.get_or_create(resource="manual_trigger"))
        database_call(lambda: _make_operator("viewer", "correct horse battery", can_trigger=False))
        database_call(lambda: _make_operator("operator", "correct horse battery", can_trigger=True))
        errors: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 1000})
                page.on("pageerror", lambda error: errors.append(str(error)))

                # Anonymous: sign-in link, no run button, no request status.
                page.goto(self.live_server_url + "/ops/")
                expect(page.get_by_role("link", name="Operator sign in")).to_be_visible()
                self.assertEqual(page.locator("#ops-run-form").count(), 0)

                # Wrong password: generic error, still anonymous.
                page.get_by_role("link", name="Operator sign in").click()
                page.get_by_label("Username").fill("operator")
                page.get_by_label("Password").fill("wrong password")
                page.get_by_role("button", name="Sign in").click()
                expect(page.locator("body")).to_contain_text("Invalid username or password.")
                self.assertEqual(page.url, self.live_server_url + "/ops/login/")

                # A signed-in account without the permission still sees no run button.
                page.get_by_label("Username").fill("viewer")
                page.get_by_label("Password").fill("correct horse battery")
                page.get_by_role("button", name="Sign in").click()
                expect(page).to_have_url(self.live_server_url + "/ops/")
                expect(page.locator("body")).to_contain_text("Signed in as viewer")
                self.assertEqual(page.locator("#ops-run-form").count(), 0)
                page.get_by_role("button", name="Log out").click()
                expect(page.get_by_role("link", name="Operator sign in")).to_be_visible()

                # The permitted operator signs in and sees the button.
                page.get_by_role("link", name="Operator sign in").click()
                page.get_by_label("Username").fill("operator")
                page.get_by_label("Password").fill("correct horse battery")
                page.get_by_role("button", name="Sign in").click()
                expect(page.locator("body")).to_contain_text("Signed in as operator")
                run_button = page.get_by_role("button", name="Run processing")
                expect(run_button).to_be_visible()

                run_button.click()
                expect(page).to_have_url(re.compile(r"request="), timeout=5000)
                status = page.locator("#ops-run-status")
                expect(status).to_contain_text("queued", timeout=5000)
                self.assertEqual(database_call(ManualRunRequest.objects.count), 1)

                # Simulate the dispatcher claiming and executing it for real, on its own
                # connection -- the same "background work happens off-page" pattern
                # `test_monitoring_e2e.py` uses for the scheduler/worker.
                pk = database_call(lambda: ManualRunRequest.objects.get().pk)
                gateway = FakeGateway(new_releases=[_identity(1)])
                result = database_call(lambda: run_manual(gateway, SystemClock(), pk))
                assert result is not None
                self.assertEqual(result.outcome, "succeeded")

                expect(status).to_contain_text("finished", timeout=5000)
                expect(status).to_contain_text(f"run #{result.run.pk}")

                artifact_dir = os.environ.get("E2E_ARTIFACT_DIR")
                if artifact_dir:
                    folder = Path(artifact_dir)
                    folder.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(folder / "bon22-operator-desktop.png"), full_page=True)

                self.assertEqual(errors, [])
            finally:
                browser.close()

    def test_an_unauthenticated_browser_post_is_rejected_as_json_403(self) -> None:
        # No session cookie and no CSRF token -- exactly what a script hitting the endpoint
        # directly (skipping the page entirely) would send; CSRF and the anonymous check both
        # produce the same JSON 403 shape, so this does not need to isolate which one fired.
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                response = page.request.post(
                    self.live_server_url + "/ops/run/", data={"request_id": "not-a-uuid"}
                )
                self.assertEqual(response.status, 403)
                self.assertEqual(response.json(), {"error": "forbidden"})
            finally:
                browser.close()
