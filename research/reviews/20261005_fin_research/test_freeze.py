"""Negative controls for freeze corruption and optimistic/missing-case evidence."""

import hashlib
import tempfile
import unittest
from pathlib import Path

import verify


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "policy.py").write_bytes(b"POLICY_VERSION = '1.0.0'\n")
        self.manifest = {
            "independent_holdout": False,
            "closed_patterns": ["*.py"],
            "sha256": {"policy.py": hashlib.sha256((self.root / "policy.py").read_bytes()).hexdigest()},
        }

    def test_unmodified_artifact_passes(self):
        verify.verify_manifest(self.root, self.manifest)

    def test_policy_change_without_version_change_is_rejected(self):
        with (self.root / "policy.py").open("ab") as file:
            file.write(b"# altered threshold\n")
        with self.assertRaisesRegex(ValueError, "changed or missing"):
            verify.verify_manifest(self.root, self.manifest)

    def test_missing_frozen_input_is_rejected(self):
        (self.root / "policy.py").unlink()
        with self.assertRaisesRegex(ValueError, "changed or missing"):
            verify.verify_manifest(self.root, self.manifest)

    def test_added_policy_helper_is_rejected(self):
        (self.root / "helper.py").write_bytes(b"# unreviewed policy helper\n")
        with self.assertRaisesRegex(ValueError, "membership"):
            verify.verify_manifest(self.root, self.manifest)

    def test_development_set_cannot_be_promoted_to_holdout(self):
        self.manifest["independent_holdout"] = True
        with self.assertRaisesRegex(ValueError, "holdout"):
            verify.verify_manifest(self.root, self.manifest)

    def test_path_outside_repository_is_rejected(self):
        self.manifest["sha256"] = {"../outside.py": "0" * 64}
        with self.assertRaisesRegex(ValueError, "escapes"):
            verify.verify_manifest(self.root, self.manifest)

    def test_missing_or_duplicate_cases_cannot_improve_denominator(self):
        for actual in [["LP-01"], ["LP-01", "LP-01"], ["LP-01", "LP-99"]]:
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                verify.complete_ids(actual, {"LP-01", "LP-04"})

    def test_valid_case_membership_is_order_independent(self):
        verify.complete_ids(["LP-04", "LP-01"], {"LP-01", "LP-04"})


if __name__ == "__main__":
    unittest.main()
