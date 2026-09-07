#!/usr/bin/env python3
"""Expose only sanitised SPK-06 health and state over HTTP."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROBE_NAME = "metacritic-ai-spk06"
STATE_PATH = Path(__file__).resolve().parent / "public" / "state.json"


class ProbeHandler(BaseHTTPRequestHandler):
    server_version = "SPK06Probe/1"
    sys_version = ""

    def send_json(self, status: HTTPStatus, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if self.path == "/health":
            payload = json.dumps(
                {"probe": PROBE_NAME, "status": "ok"},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii") + b"\n"
            self.send_json(HTTPStatus.OK, payload)
            return

        if self.path == "/state":
            try:
                payload = STATE_PATH.read_bytes()
            except FileNotFoundError:
                payload = b'{"probe":"metacritic-ai-spk06","status":"state_unavailable"}\n'
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, payload)
                return
            self.send_json(HTTPStatus.OK, payload)
            return

        payload = b'{"probe":"metacritic-ai-spk06","status":"not_found"}\n'
        self.send_json(HTTPStatus.NOT_FOUND, payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be unprivileged")
    server = ThreadingHTTPServer(("0.0.0.0", args.port), ProbeHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
