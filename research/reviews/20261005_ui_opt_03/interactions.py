"""Local event-timing samples and screenshots, not field INP or a CI gate."""

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

output = Path(".artifacts/ui-opt-03")
output.mkdir(parents=True, exist_ok=True)
records = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    for width in (1280, 390):
        context = browser.new_context(viewport={"width": width, "height": 900})
        context.add_init_script("""window.auditEvents = [];
            new PerformanceObserver(list => {
              for (const e of list.getEntries()) if (e.interactionId)
                window.auditEvents.push({name:e.name, duration:e.duration,
                  inputDelay:e.processingStart-e.startTime, interactionId:e.interactionId});
            }).observe({type:'event', buffered:true, durationThreshold:16});""")
        page = context.new_page()
        page.goto("http://127.0.0.1:18081")
        detail = page.locator(".game-list__item a").first.get_attribute("href")
        page.locator(".game-list__cover").first.wait_for()
        page.wait_for_function("document.images[0].complete")
        page.screenshot(path=str(output / f"catalog-{width}.png"))
        page.locator("#q").click()
        page.keyboard.type("Quest", delay=50)
        page.locator("#platform").focus()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(200)
        records.append(
            {
                "page": "catalog",
                "width": width,
                "actions": "Type Quest and change native select by keyboard",
                "events": page.evaluate("window.auditEvents"),
            }
        )
        page.goto("http://127.0.0.1:18081" + detail)
        page.wait_for_function("document.images[0].complete")
        page.screenshot(path=str(output / f"detail-{width}.png"), full_page=True)
        for _ in range(5):
            page.keyboard.press("Tab")
        if page.locator("details summary").count():
            page.locator("details summary").first.click()
            page.locator("details summary").first.click()
        page.wait_for_timeout(200)
        records.append(
            {
                "page": "detail",
                "width": width,
                "actions": "Five keyboard focus moves; disclosure toggles when available",
                "events": page.evaluate("window.auditEvents"),
            }
        )
        context.close()
    browser.close()
output.joinpath("interactions.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
