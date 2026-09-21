"""REV-EVAL-01 extension `1.1.0`: `INV-SENTIMENT-COVERAGE` on a frozen synthetic skewed-pool set.

The `1.0.0` oracle (`cases.json`, `metric.md`) deliberately excluded sentiment awareness. This
extension is additive: those files are untouched and a selector must still pass them. The summary
has separate Likes and Dislikes lists, so a hash sample of ten from a heavily skewed pool can leave
one side without any evidence. The single hard invariant: when the pool holds at least one review
of a side, the selection holds at least `min(3, available)` of that side, for both negative and
positive. Buckets are defined here, independently of production code, in `sentiment_cases.json`'s
`bucket_rule`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from contract import SelectionPool, SelectionResult, pool_from_case

HERE = Path(__file__).resolve().parent
MINIMUM_PER_SIDE = 3

Selector = Callable[[SelectionPool], SelectionResult]


def bucket(score: float | None, audience: str) -> str:
    if score is None:
        return "unscored"
    ratio = score / (100 if audience == "critic" else 10)
    if ratio < 0.5:
        return "negative"
    return "positive" if ratio >= 0.75 else "mixed"


def check_case(case: dict[str, Any], selector: Selector) -> dict[str, Any]:
    pool = pool_from_case(case)
    result = selector(pool)
    by_key = {review.identity_key: review for review in pool.reviews}
    available = {"negative": 0, "positive": 0}
    selected = {"negative": 0, "positive": 0}
    for review in pool.reviews:
        kind = bucket(review.score, pool.audience)
        if kind in available:
            available[kind] += 1
    for item in result.selected:
        kind = bucket(by_key[item.identity_key].score, pool.audience)
        if kind in selected:
            selected[kind] += 1
    findings = []
    for kind in ("negative", "positive"):
        needed = min(MINIMUM_PER_SIDE, available[kind])
        if selected[kind] < needed:
            findings.append(f"{kind}: selected {selected[kind]}, needed {needed}")
    expected_size = min(10, len(pool.reviews))
    if len(result.selected) != expected_size:
        findings.append(f"selected {len(result.selected)} reviews, expected {expected_size}")
    return {
        "case_id": case["id"],
        "available": available,
        "selected": selected,
        "status": "fail" if findings else "pass",
        "findings": findings,
    }


def score(selector: Selector) -> dict[str, Any]:
    document = json.loads((HERE / "sentiment_cases.json").read_text(encoding="utf-8"))
    assessments = [check_case(case, selector) for case in document["cases"]]
    failed = [a["case_id"] for a in assessments if a["status"] == "fail"]
    return {
        "eval_set_version": document["eval_set_version"],
        "invariant": document["invariant"],
        "assessments": assessments,
        "failed": failed,
        "all_pass": not failed,
    }
