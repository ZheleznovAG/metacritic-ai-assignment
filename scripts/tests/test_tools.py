"""IMP-01 / R-REP-01: deployment counterexamples, no external calls."""

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class EnvironmentUpgradeTests(unittest.TestCase):
    def test_upgrade_preserves_data_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copyfile(ROOT / "scripts/init_env.py", root / "scripts/init_env.py")
            target = root / ".env.app"
            original = "APP_ENV=local\nPOSTGRES_PASSWORD=existing-secret\nPOSTGRES_USER=legacy\n"
            target.write_text(original, encoding="utf-8")
            command = [
                sys.executable,
                "-B",
                str(root / "scripts/init_env.py"),
                "--upgrade-scaffold",
            ]
            first = subprocess.run(command, capture_output=True, check=True)
            upgraded = target.read_text(encoding="utf-8")
            self.assertTrue(upgraded.startswith(original))
            self.assertIn("WEB_DB_USER=metacritic_web\n", upgraded)
            self.assertNotIn(b"existing-secret", first.stdout + first.stderr)
            subprocess.run(command, capture_output=True, check=True)
            self.assertEqual(target.read_text(encoding="utf-8"), upgraded)


class SmokeTests(unittest.TestCase):
    def run_smoke(self, css_status):
        smoke = module("smoke")

        class Client:
            def __init__(self, *_args, **_kwargs):
                pass

            def request(self, _method, path):
                self.path = path

            def getresponse(self):
                self.status = 200 if self.path in {"/", "/health/live/", "/health/ready/"} else 404
                if self.path.startswith("/static/"):
                    self.status = css_status
                return self

            def read(self):
                if self.path.startswith("/health/"):
                    status = "ready" if self.path.endswith("ready/") else "ok"
                    return json.dumps({"status": status, "version": "test"}).encode()
                if self.path == "/":
                    return (
                        b'<form class="game-list__controls">'
                        b'<link rel="stylesheet" href="/static/app.abc.css">'
                    )
                return b"body { color: black; }"

            def getheader(self, name, default=None):
                return {"Content-Type": "text/css", "X-Content-Type-Options": "nosniff"}.get(
                    name, default
                )

            def close(self):
                pass

        with (
            patch.object(smoke, "HTTPConnection", Client),
            patch.object(sys, "argv", ["smoke", "http://localhost", "--version", "test"]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            smoke.main()

    def test_css_is_required_even_when_all_html_checks_pass(self):
        with self.assertRaisesRegex(SystemExit, "stylesheet unavailable"):
            self.run_smoke(404)

    def test_served_css_passes(self):
        self.run_smoke(200)


class ImageIdentityTests(unittest.TestCase):
    def test_stale_container_rejected_even_when_tag_matches(self):
        verifier = module("verify_image")
        expected = "sha256:" + "a" * 64
        responses = [
            [{"Id": expected, "Config": {"Labels": {"org.opencontainers.image.version": "v1"}}}],
            [{"Image": "sha256:" + "b" * 64, "State": {"Running": True}}],
        ]
        results = [
            subprocess.CompletedProcess([], 0, json.dumps(data).encode()) for data in responses
        ]
        with (
            patch.object(verifier.shutil, "which", return_value="docker"),
            patch.object(verifier.subprocess, "run", side_effect=results),
            patch.object(
                sys,
                "argv",
                [
                    "verify",
                    "--image",
                    "app:v1",
                    "--image-id",
                    expected,
                    "--version",
                    "v1",
                    "--container",
                    "web",
                ],
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "expected image"):
                verifier.main()
