#!/usr/bin/env python3
"""REV-EVAL-01 selection-oracle scorer: hard invariants, no provider calls.

Unlike evals/reviews/score_run.py (which scores saved LLM output that costs money
and time to regenerate), review selection is pure deterministic local computation.
There is nothing to "finalize" by hand: `score()` is the oracle, and `--verify`
just reruns it and checks the result still matches what was committed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

from contract import (
    MAX_REVIEW_TOKENS,
    MAX_SELECTED_REVIEWS,
    IncompleteCollectionError,
    SelectionPool,
    SelectionResult,
    count_tokens,
    mutate_review_text,
    pool_from_case,
    truncate_to_token_boundary,
)

ROOT = Path(__file__).resolve()
CASES_PATH = ROOT.with_name("cases.json")
CONTRACT_PATH = ROOT.with_name("contract.py")
INVARIANTS = (
    "INV-COMPLETE",
    "INV-CAP",
    "INV-DEDUP",
    "INV-PAGE-COVERAGE",
    "INV-DETERMINISM",
    "INV-CONTENT-INDEPENDENCE",
    "INV-NO-FABRICATION",
    "INV-MEANINGFUL-COUNT",
)
Selector = Callable[[SelectionPool], SelectionResult]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_cases() -> dict[str, Any]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def load_selector(spec: str) -> tuple[Selector, Path]:
    module_name, _, function_name = spec.partition(":")
    module = importlib.import_module(module_name)
    selector = getattr(module, function_name)
    return selector, Path(module.__file__).resolve()


def canonical_ids(result: SelectionResult) -> tuple[str, ...]:
    return tuple(item.identity_key for item in result.selected)


def check_complete(pool: SelectionPool, selector: Selector) -> tuple[str, list[str]]:
    if pool.collection_status == "complete":
        return "n/a", []
    try:
        selector(pool)
    except IncompleteCollectionError:
        return "pass", []
    return "fail", ["selector returned a result for a non-complete pool instead of raising"]


def check_cap(result: SelectionResult) -> tuple[str, list[str]]:
    findings: list[str] = []
    if len(result.selected) > MAX_SELECTED_REVIEWS:
        findings.append(f"selected {len(result.selected)} reviews, cap is {MAX_SELECTED_REVIEWS}")
    for item in result.selected:
        if item.token_count > MAX_REVIEW_TOKENS:
            findings.append(f"{item.identity_key}: {item.token_count} tokens exceeds the {MAX_REVIEW_TOKENS} cap")
        actual = count_tokens(item.text)
        if actual != item.token_count:
            findings.append(f"{item.identity_key}: reported token_count {item.token_count} != recount {actual}")
    return ("fail" if findings else "pass"), findings


def check_dedup(pool: SelectionPool, result: SelectionResult) -> tuple[str, list[str]]:
    canonical = {review.identity_key: (review.duplicate_of or review.identity_key) for review in pool.reviews}
    seen: dict[str, str] = {}
    findings: list[str] = []
    for item in result.selected:
        group = canonical.get(item.identity_key, item.identity_key)
        if group in seen:
            findings.append(f"{item.identity_key} duplicates {seen[group]} (canonical group {group})")
        else:
            seen[group] = item.identity_key
    return ("fail" if findings else "pass"), findings


def check_page_coverage(case: dict[str, Any], result: SelectionResult) -> tuple[str, list[str]]:
    required = case.get("must_include_at_least_one_of")
    if not required:
        return "n/a", []
    selected = set(canonical_ids(result))
    if selected & set(required):
        return "pass", []
    return "fail", [f"selection {sorted(selected)} includes none of {required}"]


def check_determinism(pool: SelectionPool, selector: Selector) -> tuple[str, list[str]]:
    runs = [canonical_ids(selector(pool)) for _ in range(3)]
    if len(set(runs)) == 1:
        return "pass", []
    return "fail", [f"repeated calls on an unchanged pool disagreed: {runs}"]


def check_content_independence(pool: SelectionPool, selector: Selector, base_ids: tuple[str, ...]) -> tuple[str, list[str]]:
    if len(pool.reviews) <= MAX_SELECTED_REVIEWS:
        # No exclusion decision exists to perturb: every review is selected regardless of
        # content, so a "pass" here would be vacuous rather than evidence of anything.
        return "n/a", []
    findings: list[str] = []
    for review in pool.reviews:
        mutated_pool = mutate_review_text(pool, review.identity_key, review.text + " EDITED-FOR-REV-EVAL-01-MUTATION-CHECK.")
        mutated_ids = canonical_ids(selector(mutated_pool))
        if set(mutated_ids) != set(base_ids):
            findings.append(f"editing {review.identity_key} changed the selected identity set")
    return ("fail" if findings else "pass"), findings


def check_no_fabrication(pool: SelectionPool, result: SelectionResult) -> tuple[str, list[str]]:
    by_key = {review.identity_key: review for review in pool.reviews}
    findings: list[str] = []
    for item in result.selected:
        review = by_key.get(item.identity_key)
        if review is None:
            findings.append(f"{item.identity_key} is not in the input pool")
            continue
        if item.platform_slug != review.platform_slug:
            findings.append(f"{item.identity_key}: platform_slug does not match the pool")
        if not item.truncated:
            if item.text != review.text:
                findings.append(f"{item.identity_key}: text changed without being marked truncated")
        else:
            expected = truncate_to_token_boundary(review.text)
            if item.text != expected:
                findings.append(f"{item.identity_key}: truncated text does not match token-boundary decode of the original")
            if count_tokens(review.text) <= MAX_REVIEW_TOKENS:
                findings.append(f"{item.identity_key}: marked truncated but the original was already within the cap")
    return ("fail" if findings else "pass"), findings


def check_meaningful_count(pool: SelectionPool, result: SelectionResult) -> tuple[str, list[str]]:
    findings: list[str] = []
    if result.meaningful_pool_count != pool.meaningful_count:
        findings.append(f"reported {result.meaningful_pool_count}, expected {pool.meaningful_count}")
    if result.total_pool_count != len(pool.reviews):
        findings.append(f"reported total {result.total_pool_count}, expected {len(pool.reviews)}")
    return ("fail" if findings else "pass"), findings


def score_case(case: dict[str, Any], selector: Selector) -> dict[str, Any]:
    pool = pool_from_case(case)
    invariants: dict[str, str] = {}
    findings: dict[str, list[str]] = {}

    status, notes = check_complete(pool, selector)
    invariants["INV-COMPLETE"] = status
    findings["INV-COMPLETE"] = notes

    if pool.collection_status != "complete":
        for name in INVARIANTS:
            invariants.setdefault(name, "n/a")
            findings.setdefault(name, [])
        return {"case_id": case["id"], "invariants": invariants, "findings": findings}

    result = selector(pool)
    base_ids = canonical_ids(result)

    for name, (status, notes) in {
        "INV-CAP": check_cap(result),
        "INV-DEDUP": check_dedup(pool, result),
        "INV-PAGE-COVERAGE": check_page_coverage(case, result),
        "INV-DETERMINISM": check_determinism(pool, selector),
        "INV-CONTENT-INDEPENDENCE": check_content_independence(pool, selector, base_ids),
        "INV-NO-FABRICATION": check_no_fabrication(pool, result),
        "INV-MEANINGFUL-COUNT": check_meaningful_count(pool, result),
    }.items():
        invariants[name] = status
        findings[name] = notes

    return {
        "case_id": case["id"],
        "selected_identity_keys": list(base_ids),
        "invariants": invariants,
        "findings": findings,
    }


def score(selector: Selector) -> dict[str, Any]:
    cases_document = load_cases()
    assessments = [score_case(case, selector) for case in cases_document["cases"]]
    failed = [
        f"{a['case_id']}.{name}"
        for a in assessments
        for name, status in a["invariants"].items()
        if status == "fail"
    ]
    return {
        "eval_set_version": cases_document["eval_set_version"],
        "assessments": assessments,
        "all_pass": not failed,
        "failed": failed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selector",
        default="baseline_naive:select_reviews",
        help="module:function to evaluate (default: the naive baseline)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--save", type=Path, help="write the report and artifact hashes to this path")
    mode.add_argument("--verify", type=Path, help="recompute and compare against a saved report")
    return parser


def artifact_hashes(selector_path: Path) -> dict[str, str]:
    return {
        "cases_sha256": sha256_bytes(CASES_PATH.read_bytes()),
        "contract_sha256": sha256_bytes(CONTRACT_PATH.read_bytes()),
        "selector_sha256": sha256_bytes(selector_path.read_bytes()),
    }


def main() -> int:
    args = build_parser().parse_args()
    selector, selector_path = load_selector(args.selector)
    report = score(selector)

    if args.save:
        payload = {
            "selector": args.selector,
            **artifact_hashes(selector_path),
            "report": report,
        }
        args.save.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Saved: {args.save}")
        print(f"all_pass={report['all_pass']} failed={report['failed']}")
        return 0

    if args.verify:
        saved = json.loads(args.verify.read_text(encoding="utf-8"))
        selector, selector_path = load_selector(saved["selector"])
        current_hashes = artifact_hashes(selector_path)
        for key, value in current_hashes.items():
            if saved.get(key) != value:
                print(f"ERROR: {key} does not match the saved report", file=sys.stderr)
                return 1
        fresh = score(selector)
        if fresh != saved["report"]:
            print("ERROR: recomputed report does not match the saved report", file=sys.stderr)
            return 1
        print(
            f"Saved report verified: {saved['selector']}, "
            f"all_pass={fresh['all_pass']}, no recomputation drift."
        )
        return 0

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
