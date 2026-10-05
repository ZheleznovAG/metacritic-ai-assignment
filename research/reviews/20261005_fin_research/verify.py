"""Read-only FIN-RESEARCH freeze/integrity audit; no provider calls or quality waiver."""

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "docs/evidence/fin-research/freeze.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def complete_ids(actual, expected):
    actual = list(actual)
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError("Missing, duplicate or unexpected evaluation cases")


def verify_manifest(root, manifest):
    if manifest["independent_holdout"] is not False:
        raise ValueError("Existing development sets cannot be claimed as holdout")
    root = root.resolve()
    paths = manifest["sha256"]
    for name, expected in paths.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Freeze path escapes repository")
        if not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError(f"Invalid hash: {name}")
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f"Frozen artifact changed or missing: {name}")
    for pattern in manifest.get("closed_patterns", []):
        current = {p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file()}
        frozen = {name for name in paths if Path(name).match(pattern)}
        if current != frozen:
            raise ValueError(f"Frozen artifact membership changed: {pattern}")


def load(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


def scorer(root, name):
    path = root / "evals/letsplays" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def similarity_summary(root):
    report = load(root, "evals/similarity/text_report_v2.json")
    for version, file in [("1.0.0", "text_labels.json"), ("2.0.0", "text_labels_v2.json")]:
        path = root / "evals/similarity" / file
        labels = json.loads(path.read_text(encoding="utf-8"))
        expected = [row["source_game_id"] for row in labels["queries"]]
        complete_ids(expected, expected)
        data = report["sets"][version]
        if digest(path) != data["labels_sha256"]:
            raise ValueError("Similarity label hash mismatch")
        for method in data["methods"].values():
            complete_ids(method["per_query_ndcg"], expected)
    old, new = "text-hybrid@2.0.0", "text-hybrid@3.0.0"
    first, second = report["sets"]["1.0.0"]["methods"], report["sets"]["2.0.0"]["methods"]
    regression = round(first[old]["mean_ndcg_at_5"] - first[new]["mean_ndcg_at_5"], 3)
    numeric = {
        "set_two_improves_by_at_least_0_05": second[new]["mean_ndcg_at_5"] >= second[old]["mean_ndcg_at_5"] + 0.05,
        "set_two_precision_not_lower": second[new]["precision"] >= second[old]["precision"],
        "set_one_drop_at_most_0_03": regression <= 0.03,
        "coverage_not_lower": report["coverage"][new] >= report["coverage"][old],
    }
    if regression != 0.227 or numeric["set_one_drop_at_most_0_03"]:
        raise ValueError("Disclosed similarity failure was removed")
    return {"snapshot_sha256": report["snapshot_sha256"], "snapshot_games": report["snapshot_games"],
            "numeric_criteria": numeric, "set_one_regression": regression,
            "full_quality_bar_passed": False, "independent_holdout": False,
            "hard_invariants": "Verified by original report/application tests; not inferred from aggregate scores"}


def letsplay_summary(root):
    selection = load(root, "evals/letsplays/selector_report.json")
    pool, labels = load(root, "evals/letsplays/candidates.json"), load(root, "evals/letsplays/labels.json")
    expected_titles = [row["title"] for row in labels["games"]]
    complete_ids((row["title"] for row in selection["trace"]), expected_titles)
    choices = {row["title"]: row["chosen"] for row in selection["trace"]}
    result = scorer(root, "score_selection").score(choices, labels, pool)
    if {key: result[key] for key in selection["result"]} != selection["result"]:
        raise ValueError("Selector score disagrees with published decisions")
    cases = load(root, "evals/letsplays/conclusion_cases.json")
    expected = [row["case_id"] for row in cases["cases"]]
    complete_ids(expected, expected)
    run = load(root, "evals/letsplays/conclusion_run_2_1_0.json")
    complete_ids((row["case_id"] for row in run["cases"]), expected)
    grades = load(root, "evals/letsplays/conclusion_grades.json")
    complete_ids(grades["runs"]["2.1.0"], expected)
    conclusion = scorer(root, "score_conclusions").judge(grades["runs"]["2.1.0"])
    if (conclusion["total"], conclusion["maximum"], conclusion["passed"], conclusion["blocking"]) != (111, 132, False, ["LP-04"]):
        raise ValueError("Disclosed conclusion failure was removed")
    valid = sum(not row["validation_errors"] for row in run["cases"])
    return {"selection": selection["result"], "conclusion": conclusion,
            "structural_validity": {"valid": valid, "cases": len(expected)},
            "independent_holdout": False, "experimental": True,
            "limit": "Published decisions/grades rescored; semantic judgments are not independently regraded"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    verify_manifest(ROOT, manifest)
    result = {"baseline": manifest["baseline"], "freeze_version": manifest["version"],
              "frozen_files": len(manifest["sha256"]), "integrity_passed": True,
              "similarity": similarity_summary(ROOT), "letsplay": letsplay_summary(ROOT),
              "limits": "Integrity/recalculation only. Existing accepted failures remain; no independent holdout pass."}
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
