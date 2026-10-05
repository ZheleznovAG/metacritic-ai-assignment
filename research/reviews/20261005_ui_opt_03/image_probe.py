import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

rows = []
data = json.loads(Path(".artifacts/ui-opt-03/browser.json").read_text())
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    for image in data[0]["metrics"]["images"][:3]:
        url = image["src"]
        for variant in (
            url,
            url.replace("width=1200", "width=300").replace("height=675", "height=400"),
        ):
            response = page.goto(variant, wait_until="load")
            body = response.body()
            rows.append(
                {
                    "url": variant,
                    "status": response.status,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "contentType": response.headers.get("content-type"),
                }
            )
    browser.close()
Path(".artifacts/ui-opt-03/image-probe.json").write_text(json.dumps(rows, indent=2))
print(json.dumps(rows, indent=2))
