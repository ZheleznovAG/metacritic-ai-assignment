"""REV-EVAL-01 extension `1.2.0`: `INV-MEANINGFUL-ELIGIBILITY` on a frozen synthetic blank-review set.

The 2026-09-18 audit (`MA-01`) showed that blank reviews could occupy the bounded sample: with 20
blank and 3 meaningful user reviews only one meaningful review reached the model, so a game with
three usable reviews was reported as `insufficient_data`. This extension is additive: the `1.0.0`
and `1.1.0` files are untouched and a selector must still pass them. The single hard invariant: the
selection contains exactly `min(10, M)` meaningful reviews, where `M` is the number of distinct
meaningful canonical groups in the pool. Ground truth is each review's authored `meaningful` field,
defined here independently of production code.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from contract import SelectionPool, SelectionResult, pool_from_case

HERE = Path(__file__).resolve().parent
MAXIMUM_SELECTED = 10

Selector = Callable[[SelectionPool], SelectionResult]


def check_case(case: dict[str, Any], selector: Selector) -> dict[str, Any]:
    pool = pool_from_case(case)
    result = selector(pool)
    by_key = {review.identity_key: review for review in pool.reviews}
    available = len(
        {review.duplicate_of or review.identity_key for review in pool.reviews if review.meaningful}
    )
    selected = sum(1 for item in result.selected if by_key[item.identity_key].meaningful)
    expected = min(MAXIMUM_SELECTED, available)
    findings = []
    if selected != expected:
        findings.append(f"selected {selected} meaningful reviews, expected {expected}")
    return {
        "case_id": case["id"],
        "meaningful_available": available,
        "meaningful_selected": selected,
        "status": "fail" if findings else "pass",
        "findings": findings,
    }


def score(selector: Selector) -> dict[str, Any]:
    document = json.loads((HERE / "meaningful_cases.json").read_text(encoding="utf-8"))
    assessments = [check_case(case, selector) for case in document["cases"]]
    failed = [a["case_id"] for a in assessments if a["status"] == "fail"]
    return {
        "eval_set_version": document["eval_set_version"],
        "invariant": document["invariant"],
        "assessments": assessments,
        "failed": failed,
        "all_pass": not failed,
    }
