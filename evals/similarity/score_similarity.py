"""SIM-EVAL-01: frozen graded-relevance evaluator, with no ranking policy inside it."""

import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path

from contract import MAX_RESULTS, Ranker, catalog_from_case

ROOT = Path(__file__).resolve().parent
FROZEN_FILES = ("cases.json", "metric.md", "contract.py", "score_similarity.py")
INVARIANTS = (
    "INV-VALID-RESULT", "INV-CAP", "INV-SAVED", "INV-NO-SELF", "INV-UNIQUE",
    "INV-NONMATCH", "INV-DETERMINISTIC", "INV-QUERY",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_cases() -> dict:
    result = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    validate_cases(result)
    return result


def validate_cases(document: dict) -> None:
    require(document["version"] == "1.0.0", "Unexpected oracle version")
    thresholds = document["thresholds"]
    require(0 < thresholds["min_case_ndcg_at_5"] <= thresholds["macro_ndcg_at_5"] <= 1,
            "Invalid relevance thresholds")
    case_ids = [case["id"] for case in document["cases"]]
    require(bool(case_ids) and len(case_ids) == len(set(case_ids)), "Duplicate/empty case IDs")
    positives = 0
    for case in document["cases"]:
        prefix = case["id"] + ": "
        require(type(case["query_id"]) is int, prefix + "query ID must be an integer")
        ids = []
        for game in case["catalog"]:
            require(type(game["id"]) is int and game["id"] > 0, prefix + "invalid saved ID")
            ids.append(game["id"])
            require(isinstance(game["title"], str) and bool(game["title"]), prefix + "missing title")
            require(game["developer"] is None or isinstance(game["developer"], str),
                    prefix + "invalid developer")
            for field in ("genres", "platforms"):
                require(isinstance(game[field], list) and all(isinstance(v, str) for v in game[field]),
                        prefix + "invalid " + field)
        require(len(ids) == len(set(ids)), prefix + "duplicate saved IDs")
        judged = [item["game_id"] for item in case["judgments"]]
        require(len(judged) == len(set(judged)), prefix + "duplicate judgments")
        require(set(judged) == set(ids) - {case["query_id"]}, prefix + "incomplete judgments")
        for item in case["judgments"]:
            require(type(item["grade"]) is int and item["grade"] in (0, 1, 2), prefix + "invalid grade")
            require(isinstance(item["reason"], str) and bool(item["reason"].strip()),
                    prefix + "missing judgment rationale")
        has_positive = any(item["grade"] > 0 for item in case["judgments"])
        require(not has_positive or case["query_id"] in ids, prefix + "positive absent-query judgment")
        positives += has_positive
    require(positives > 0, "No positive relevance cases")


def dcg(grades: list[int]) -> float:
    return sum((2 ** grade - 1) / math.log2(rank + 2)
               for rank, grade in enumerate(grades[:MAX_RESULTS]))


def ndcg(selected: list[int], judgments: dict[int, int]) -> float | None:
    ideal = dcg(sorted(judgments.values(), reverse=True))
    if ideal == 0:
        return None
    # Repeated or external IDs cannot manufacture gain. Hard invariants reject them too.
    seen = set()
    grades = []
    for game_id in selected[:MAX_RESULTS]:
        grades.append(judgments.get(game_id, 0) if game_id not in seen else 0)
        seen.add(game_id)
    return dcg(grades) / ideal


def evaluate_case(case: dict, ranker: Ranker) -> dict:
    catalog = catalog_from_case(case)
    query = case["query_id"]
    grades = {item["game_id"]: item["grade"] for item in case["judgments"]}
    checks = dict.fromkeys(INVARIANTS, True)
    errors = []
    orders = (catalog, catalog, tuple(reversed(catalog)), catalog[1:] + catalog[:1],
              tuple(sorted(catalog, key=lambda game: game.id)))
    outputs = []
    for permutation in orders:
        try:
            result = ranker(query, permutation)
            if not isinstance(result, (list, tuple)) or any(type(pk) is not int for pk in result):
                checks["INV-VALID-RESULT"] = False
                errors.append("ranker must return a list/tuple of integer saved IDs")
                outputs.append([])
                continue
            selected = list(result)
            outputs.append(selected)
            known = {game.id for game in catalog}
            checks["INV-CAP"] &= len(selected) <= MAX_RESULTS
            checks["INV-SAVED"] &= all(pk in known for pk in selected)
            checks["INV-NO-SELF"] &= query not in selected
            checks["INV-UNIQUE"] &= len(selected) == len(set(selected))
            checks["INV-NONMATCH"] &= all(grades.get(pk, 0) > 0 for pk in selected)
            checks["INV-QUERY"] &= query in known or not selected
        except Exception as error:
            checks["INV-VALID-RESULT"] = False
            errors.append(type(error).__name__)
            outputs.append([])
    checks["INV-DETERMINISTIC"] = all(output == outputs[0] for output in outputs)
    relevance = [ndcg(output, grades) for output in outputs]
    measured = [value for value in relevance if value is not None]
    return {"case_id": case["id"], "selected_ids": outputs[0], "hard_invariants": checks,
            "ndcg_at_5": min(measured) if measured else None, "errors": sorted(set(errors))}


def evaluate(document: dict, ranker: Ranker) -> dict:
    validate_cases(document)
    cases = [evaluate_case(case, ranker) for case in document["cases"]]
    values = [case["ndcg_at_5"] for case in cases if case["ndcg_at_5"] is not None]
    macro = sum(values) / len(values)
    floor = min(values)
    hard_pass = all(all(case["hard_invariants"].values()) for case in cases)
    quality_pass = (macro >= document["thresholds"]["macro_ndcg_at_5"]
                    and floor >= document["thresholds"]["min_case_ndcg_at_5"])
    return {"oracle_version": document["version"], "thresholds": document["thresholds"],
            "positive_case_count": len(values), "empty_or_negative_case_count": len(cases) - len(values),
            "macro_ndcg_at_5": macro, "min_case_ndcg_at_5": floor,
            "hard_invariants_pass": hard_pass, "quality_pass": quality_pass,
            "accepted": hard_pass and quality_pass, "cases": cases}


def verify_manifest() -> dict:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    require(set(manifest["sha256"]) == set(FROZEN_FILES), "Incomplete frozen manifest")
    for name in FROZEN_FILES:
        require(manifest["sha256"][name] == digest(ROOT / name), "Frozen oracle drift: " + name)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="verify structure and frozen file hashes")
    parser.add_argument("--ranker", help="module:function implementing the frozen contract")
    parser.add_argument("--policy-version")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    document = load_cases()
    manifest = verify_manifest()
    if args.verify:
        print(f"PASS SIM-EVAL-01 integrity: {len(document['cases'])} cases; version {document['version']}; owner acceptance is recorded only in action_plan.md")
        return
    if not args.ranker or not args.policy_version or not args.output:
        parser.error("provide --verify or --ranker module:function --policy-version VERSION --output PATH")
    module_name, separator, function_name = args.ranker.partition(":")
    require(bool(separator and module_name and function_name), "Invalid ranker specification")
    module = importlib.import_module(module_name)
    result = evaluate(document, getattr(module, function_name))
    result.update(oracle_manifest=manifest, policy_version=args.policy_version,
                  ranker=args.ranker, ranker_module_sha256=digest(Path(module.__file__)))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in result.items() if key not in ("cases", "oracle_manifest")}))
    raise SystemExit(0 if result["accepted"] else 1)


if __name__ == "__main__":
    main()
