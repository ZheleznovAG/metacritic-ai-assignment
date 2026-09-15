"""Small external read-only smoke test for the IMP-01 scaffold; no browser dependency."""

import argparse
import json
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlsplit


class Stylesheets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "link" and "stylesheet" in (values.get("rel") or "").split():
            href = values.get("href") or ""
            parsed = urlsplit(href)
            if parsed.scheme or parsed.netloc or not href.startswith("/static/"):
                raise SystemExit("Smoke failed: unexpected stylesheet location")
            self.paths.append(href)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    target = urlsplit(arguments.url)
    if target.scheme not in {"http", "https"} or not target.hostname or target.username:
        parser.error("Provide an HTTP(S) base URL without credentials")
    if target.path not in {"", "/"} or target.query or target.fragment:
        parser.error("Provide a base URL without a path, query or fragment")
    connection_type = HTTPSConnection if target.scheme == "https" else HTTPConnection
    stylesheets = Stylesheets()
    for path, expected_status in (
        ("/", 200),
        ("/health/live/", 200),
        ("/health/ready/", 200),
        ("/.env", 404),
        ("/.env.app", 404),
        ("/admin/", 404),
        ("/unknown", 404),
    ):
        client = connection_type(target.hostname, target.port, timeout=10)
        client.request("GET", path)
        response = client.getresponse()
        body = response.read()
        if response.status != expected_status:
            raise SystemExit(
                f"Smoke failed: {path}, expected {expected_status}, got {response.status}"
            )
        if path.startswith("/health/"):
            data = json.loads(body)
            expected = "ready" if path.endswith("ready/") else "ok"
            if data != {"status": expected, "version": arguments.version}:
                raise SystemExit(f"Smoke failed: {path}, unexpected payload")
        if path == "/" and b'class="game-list__controls"' not in body:
            raise SystemExit("Smoke failed: game list search/filter form missing")
        if path == "/":
            stylesheets.feed(body.decode("utf-8"))
        if response.getheader("X-Content-Type-Options") != "nosniff":
            raise SystemExit(f"Smoke failed: {path}, nosniff missing")
        client.close()
        print(f"PASS {path}: {expected_status}")
    if not stylesheets.paths:
        raise SystemExit("Smoke failed: stylesheet missing from page")
    for path in stylesheets.paths:
        client = connection_type(target.hostname, target.port, timeout=10)
        client.request("GET", path)
        response = client.getresponse()
        body = response.read()
        content_type = response.getheader("Content-Type", "").split(";", 1)[0]
        if response.status != 200 or content_type != "text/css" or not body.strip():
            raise SystemExit(f"Smoke failed: stylesheet unavailable: {path}")
        client.close()
        print(f"PASS {path}: CSS served")


if __name__ == "__main__":
    main()
