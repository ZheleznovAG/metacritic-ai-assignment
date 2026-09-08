"""Negative controls for the PLN-03 documentation audit; no application runtime."""

import unittest

from check_plan import check, read_sources


class PlanAuditTests(unittest.TestCase):
    def setUp(self):
        self.docs = read_sources()

    def replace(self, document, old, new):
        self.assertIn(old, self.docs[document])
        self.docs[document] = self.docs[document].replace(old, new, 1)

    def test_baseline(self):
        report = check(self.docs)
        self.assertEqual(report["must_requirements"], 28)
        self.assertEqual(report["risks"], 24)
        self.assertEqual(len(report["scenarios"]), 4)

    def test_missing_must_mapping(self):
        self.replace("implementation", "| `RUN-01` | `IMP-03` | `PUB-02, REL-01` |", "")
        with self.assertRaisesRegex(ValueError, "Requirement coverage mismatch"):
            check(self.docs)

    def test_missing_risk_mapping(self):
        self.replace("implementation", "| `R-PLN-01` | `PLN-03, BON-00` |", "")
        with self.assertRaisesRegex(ValueError, "Risk coverage mismatch"):
            check(self.docs)

    def test_cycle(self):
        self.replace("action", "| IMP-01 | base |", "| IMP-03 | base |")
        with self.assertRaisesRegex(ValueError, "Dependency cycle"):
            check(self.docs)

    def test_hardening_gate_bypass(self):
        self.replace("action", "#hrd-01) | G4 |", "#hrd-01) | IMP-02 |")
        with self.assertRaisesRegex(ValueError, "Gate bypass"):
            check(self.docs)

    def test_bonus_gate_bypass(self):
        self.replace("action", "#bon-00) | G6 |", "#bon-00) | G5 |")
        with self.assertRaisesRegex(ValueError, "Gate bypass|disconnected"):
            check(self.docs)

    def test_freeze_before_readme(self):
        self.replace("action", "| REL-02, REL-03 | base |", "| REL-03 | base |")
        with self.assertRaisesRegex(ValueError, "Required ordering|disconnected"):
            check(self.docs)

    def test_unconditional_bonus_dependency(self):
        self.replace("action", "BON-12?, BON-22?", "BON-12, BON-22?")
        with self.assertRaisesRegex(ValueError, "Inactive mandatory dependency"):
            check(self.docs)

    def test_wrong_subtask_sum(self):
        self.replace("implementation", "Runtime/lock и Django bootstrap — 2 ч",
                     "Runtime/lock и Django bootstrap — 3 ч")
        with self.assertRaisesRegex(ValueError, "Timebox parts do not sum"):
            check(self.docs)

    def test_unknown_task(self):
        self.replace("implementation", "| `RUN-01` | `IMP-03` |",
                     "| `RUN-01` | `IMP-99` |")
        with self.assertRaisesRegex(ValueError, "Missing/unknown task"):
            check(self.docs)

    def test_duplicate_task(self):
        row = next(line for line in self.docs["action"].splitlines()
                   if line.startswith("| [IMP-01]"))
        self.docs["action"] += "\n" + row + "\n"
        with self.assertRaisesRegex(ValueError, "Duplicate node"):
            check(self.docs)

    def test_must_mapped_to_bonus(self):
        self.replace("implementation", "| `RUN-01` | `IMP-03` |",
                     "| `RUN-01` | `BON-21` |")
        with self.assertRaisesRegex(ValueError, "Must requirement depends on Bonus"):
            check(self.docs)


if __name__ == "__main__":
    unittest.main()
