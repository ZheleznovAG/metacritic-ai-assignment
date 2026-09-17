"""DEL-03 / NFR-06: adversarial export boundaries, using invented data only."""

import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from scripts.export_ai_history import (
    Redactor,
    collect,
    export,
    in_project,
    read_session,
    select,
    timestamp,
)
from scripts.verify_ai_history import verify


class HistoryTests(unittest.TestCase):
    def test_project_boundary_handles_subfolders_but_not_sibling(self):
        self.assertTrue(in_project(r"C:\work\repo\docs", "c:/work/repo"))
        self.assertFalse(in_project("c:/work/repo-other", "c:/work/repo"))

    def test_start_boundary_uses_declared_timezone(self):
        self.assertEqual(timestamp("2026-09-01T00:00:00+07:00"), timestamp("2026-08-31T17:00:00Z"))
        with self.assertRaises(ValueError):
            timestamp("2026-09-01")

    def test_credentials_in_fields_keys_and_nested_json(self):
        redactor = Redactor(["private-value-fixture"])
        source = {
            "password": "invented-password",
            "private-value-fixture": "key must be redacted too",
            "arguments": json.dumps({"api_key": "invented-key", "note": "private-value-fixture"}),
        }
        result = redactor.walk(source)
        encoded = json.dumps(result)
        for value in ("invented-password", "private-value-fixture", "invented-key"):
            self.assertNotIn(value, encoded)
        self.assertEqual(json.loads(result["arguments"])["api_key"], "[REDACTED]")

    def test_unknown_credentials_and_quoted_assignments(self):
        source = (
            'PASSWORD="invented secret with spaces"\n'
            "postgresql://fixture:invented-password@localhost/db\n"
            "Authorization: Bearer invented-bearer-value-long-enough\n"
            "sk-proj-" + "x" * 40
        )
        clean = Redactor().text(source)
        for secret in ("invented secret", "invented-password", "invented-bearer", "x" * 40):
            self.assertNotIn(secret, clean)

    def test_paths_escaping_and_email_privacy(self):
        redactor = Redactor([r"C:\Users\fixture\work"], "owner@example.test")
        source = {
            "cwd": r"C:\Users\fixture\work",
            "args": json.dumps({"path": r"C:\Users\fixture\work"}),
            "note": "owner@example.test thirdparty@example.test C:/Users/fixture/other",
        }
        clean = json.dumps(redactor.walk(source))
        self.assertNotIn("fixture", clean)
        self.assertNotIn("thirdparty@", clean)
        self.assertIn("owner@example.test", clean)

    def test_opaque_images_are_not_published(self):
        source = {"source": {"type": "base64", "data": "secret-pixels"}}
        self.assertNotIn("secret-pixels", json.dumps(Redactor().walk(source)))

    def test_truncated_private_key_is_removed_without_an_end_marker(self):
        source = "-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-key-fragment\n"
        result = Redactor().text(source)
        self.assertEqual(result, "[REDACTED]")

    def test_openssh_fragment_without_pem_header_is_removed(self):
        fragment = "b3BlbnNzaC1rZXktdjE" + "A" * 60
        self.assertEqual(Redactor().text(fragment), "[REDACTED]")

    def test_msys_and_wsl_home_paths_are_private(self):
        for path in ("/c/Users/fixture/.ssh/key", "/mnt/c/Users/fixture/.ssh/key"):
            self.assertNotIn("fixture", Redactor().text(path))

    def test_legitimate_hashes_and_numeric_usage_survive(self):
        digest = "0123456789abcdef" * 4
        row = {"commit": digest[:40], "image": "sha256:" + digest, "total_tokens": 2300}
        self.assertEqual(Redactor().walk(row), row)

    def test_login_context_does_not_replace_ordinary_prose(self):
        redactor = Redactor(private_usernames=["operator"])
        self.assertEqual(redactor.text("the operator runs a check."), "the operator runs a check.")
        self.assertNotIn("operator@", redactor.text("ssh operator@host.example"))

    def test_partial_or_invalid_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_bytes(b'{"message":"unfinished"}')
            with self.assertRaises(ValueError):
                read_session(path)
            path.write_bytes(b"not-json\n")
            with self.assertRaises(ValueError):
                read_session(path)

    def test_git_correlation_is_mandatory(self):
        session = {"tool": "claude", "path": Path("session.jsonl")}
        with self.assertRaises(ValueError):
            select([session], [], Counter())
        with self.assertRaises(ValueError):
            select(
                [session],
                [
                    {
                        "tool": "claude",
                        "id": "session",
                        "include": True,
                        "reason": "same date is insufficient",
                    }
                ],
                Counter(),
            )

    def test_collection_and_zip_exclude_other_project_and_preserve_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex, claude = root / "codex", root / "claude"
            codex.mkdir()
            claude.mkdir()
            for name, cwd, date in (
                ("one", "c:/work/repo", "2026-09-03T01:00:00Z"),
                ("two", "c:/work/repo/docs", "2026-09-04T01:00:00Z"),
                ("sibling", "c:/work/repo-other", "2026-09-04T01:00:00Z"),
            ):
                rows = [
                    {"type": "session_meta", "payload": {"cwd": cwd, "timestamp": date}},
                    {"type": "response_item", "payload": {"text": "private-fixture"}},
                ]
                (codex / (name + ".jsonl")).write_text(
                    "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
                )
            since = timestamp("2026-09-01T00:00:00+07:00")
            sessions, counts = collect(codex, claude, "c:/work/repo", since)
            self.assertEqual([s["path"].stem for s in sessions], ["one", "two"])
            self.assertEqual(counts["outside_project_or_mixed"], 1)
            output = root / "export.zip"
            report = export(sessions, Redactor(["private-fixture"]), output, since, counts)
            self.assertEqual(report["lines"], 4)
            with ZipFile(output) as archive:
                self.assertEqual(len(archive.namelist()), 3)
                for member in archive.namelist():
                    self.assertNotIn(b"private-fixture", archive.read(member))
                self.assertIsNone(archive.testzip())

    def test_independent_verifier_rejects_secret_even_with_consistent_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export.zip"
            member = "001_claude_fixture.jsonl"
            data = b'{"output":"postgresql://fixture:unshared-value@localhost/db"}\n'
            manifest = [{"file": member, "lines": 1, "sha256": hashlib.sha256(data).hexdigest()}]
            with ZipFile(output, "w") as archive:
                archive.writestr(member, data)
                archive.writestr("manifest.json", json.dumps(manifest))
            audit = {
                "manifest": manifest,
                "lines": 1,
                "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            }
            selection = {"decisions": [{"tool": "claude", "id": "fixture", "include": True}]}
            with self.assertRaisesRegex(ValueError, "privacy scan failed"):
                verify(output, audit, selection, [])


if __name__ == "__main__":
    unittest.main()
