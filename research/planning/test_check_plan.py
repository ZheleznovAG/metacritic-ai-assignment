"""Negative controls for the PLN-03 documentation audit; no application runtime."""

import unittest

from check_plan import check, key, read_sources


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

    def set_scope(self, scope):
        current = next(line for line in self.docs["action"].splitlines()
                       if line.startswith("- Bonus scope:"))
        self.replace("action", current, f"- Bonus scope: `{scope}`.")

    def completed_scope(self, scope):
        self.set_scope(scope)
        selected = {"none": set(), "bonus1": {"bonus1"},
                    "bonus2": {"bonus2"}, "both": {"bonus1", "bonus2"}}[scope]
        lines = []
        for line in self.docs["action"].splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if line.startswith("|") and len(cells) == 5 and key(cells[0]):
                node = key(cells[0])
                if cells[2] != "base" and cells[2] not in selected:
                    cells[3:] = ["Dropped", "Excluded by BON-00 scope decision"]
                elif not node.startswith("REL-") and node != "G7":
                    cells[3:] = ["Verified", "[Test evidence](intake.md)"]
                line = "| " + " | ".join(cells) + " |"
            lines.append(line)
        self.docs["action"] = "\n".join(lines)

    def test_completed_optional_scopes(self):
        for scope in ("none", "bonus1", "bonus2", "both"):
            with self.subTest(scope=scope):
                self.docs = read_sources()
                self.completed_scope(scope)
                self.assertEqual(check(self.docs)["selected_bonus_scope"], scope)

    def test_missing_verified_evidence(self):
        self.replace("action", "[Intake](intake.md)",
                     "[Intake](docs/evidence/does-not-exist.md)")
        with self.assertRaisesRegex(ValueError, "Missing local evidence artifact"):
            check(self.docs)

    def test_mandatory_task_cannot_be_dropped(self):
        self.replace("action", "| base | Verified |", "| base | Dropped |")
        with self.assertRaisesRegex(ValueError, "Mandatory task cannot be Dropped"):
            check(self.docs)

    def test_scope_requires_owner_decision(self):
        self.set_scope("none")
        row = next(line for line in self.docs["action"].splitlines()
                   if line.startswith("| [BON-00]"))
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        cells[3] = "Planned"
        self.replace("action", row, "| " + " | ".join(cells) + " |")
        with self.assertRaisesRegex(ValueError, "verified BON-00"):
            check(self.docs)

    def test_selected_bonus_still_blocks_gate(self):
        self.completed_scope("bonus1")
        self.replace("action", "#bon-12) | BON-11 | bonus1 | Verified |",
                     "#bon-12) | BON-11 | bonus1 | Planned |")
        with self.assertRaisesRegex(ValueError, "Unsatisfied prerequisite of GB"):
            check(self.docs)

    def test_selected_bonus_cannot_be_dropped(self):
        self.completed_scope("bonus2")
        self.replace("action", "#bon-22) | BON-21 | bonus2 | Verified |",
                     "#bon-22) | BON-21 | bonus2 | Dropped |")
        with self.assertRaisesRegex(ValueError, "not excluded by accepted scope"):
            check(self.docs)


if __name__ == "__main__":
    unittest.main()
