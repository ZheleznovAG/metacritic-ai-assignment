"""Reproduce IMP-06's two-policy comparison without changing the frozen oracle."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import candidates
import score_similarity
from similarity import policy

SOURCES = ("app/catalog/genres.py", "app/similarity/policy.py",
           "evals/similarity/candidates.py", "evals/similarity/compare.py")


def comparison():
    manifest = score_similarity.verify_manifest()
    document = score_similarity.load_cases()
    methods = {}
    for name, version, ranker in (
        ("weighted-metadata", "0.1.0", candidates.weighted_metadata),
        (policy.POLICY_ID, policy.POLICY_VERSION, candidates.genre_jaccard),
    ):
        methods[name] = dict(policy_version=version, **score_similarity.evaluate(document, ranker))
    selected = policy.POLICY_ID if methods[policy.POLICY_ID]["accepted"] else None
    return {"task": "IMP-06", "oracle_manifest": manifest,
            "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES},
            "methods": methods, "selected_policy": selected,
            "selection_rule": "Choose the simpler genre-only baseline if it passes every frozen criterion; otherwise no release policy is selected."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="publish the measured comparison")
    args = parser.parse_args()
    report = comparison()
    path = Path(__file__).with_name("comparison_report.json")
    if args.write:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        assert json.loads(path.read_text(encoding="utf-8")) == report, "Comparison/source drift; review before replacing evidence"
    for name, result in report["methods"].items():
        print(name, "mean=", result["macro_ndcg_at_5"], "floor=", result["min_case_ndcg_at_5"],
              "invariants=", result["hard_invariants_pass"], "accepted=", result["accepted"])
        for case in result["cases"]:
            failed = [name for name, passed in case["hard_invariants"].items() if not passed]
            if failed:
                print(" ", case["case_id"], failed)
    print("Selected:", report["selected_policy"])
    return 0 if report["selected_policy"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
