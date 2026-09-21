#!/usr/bin/env python3
"""Score the real IMP-04 candidate (`reviews.selection`) against the frozen REV-EVAL-01 oracle.

Does not modify contract.py/cases.json/metric.md/score_selection.py/baseline_naive.py — it only
adapts between two field-identical, independently-defined dataclass sets (this eval's frozen
`contract.py` and the production `reviews/selection.py`, which must not depend on this `evals/`
tree at runtime) so the existing scorer can run against real production code.

Usage: run with `app/` on PYTHONPATH so `import reviews.selection` resolves, e.g. from the repo
root: `PYTHONPATH=app .venv/Scripts/python.exe evals/review_selection/verify_candidate.py`
"""

from __future__ import annotations

import json

import contract as frozen
import score_selection
import score_sentiment
from reviews import selection as candidate


def _to_candidate_pool(pool: frozen.SelectionPool) -> candidate.SelectionPool:
    reviews = tuple(
        candidate.ReviewRecord(
            identity_key=r.identity_key,
            platform_slug=r.platform_slug,
            page_offset=r.page_offset,
            language=r.language,
            score=r.score,
            text=r.text,
            meaningful=r.meaningful,
            duplicate_of=r.duplicate_of,
        )
        for r in pool.reviews
    )
    return candidate.SelectionPool(
        audience=pool.audience,
        game_slug=pool.game_slug,
        collection_status=pool.collection_status,
        reviews=reviews,
    )


def _to_frozen_result(result: candidate.SelectionResult) -> frozen.SelectionResult:
    selected = tuple(
        frozen.SelectedReview(
            identity_key=item.identity_key,
            platform_slug=item.platform_slug,
            text=item.text,
            truncated=item.truncated,
            token_count=item.token_count,
        )
        for item in result.selected
    )
    return frozen.SelectionResult(
        selected=selected,
        meaningful_pool_count=result.meaningful_pool_count,
        total_pool_count=result.total_pool_count,
    )


def select_reviews(pool: frozen.SelectionPool) -> frozen.SelectionResult:
    try:
        candidate_result = candidate.select_reviews(_to_candidate_pool(pool))
    except candidate.IncompleteCollectionError as error:
        raise frozen.IncompleteCollectionError(str(error)) from error
    return _to_frozen_result(candidate_result)


def main() -> int:
    report = score_selection.score(select_reviews)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    baseline_failed = {
        "first_page_bias_trap.INV-PAGE-COVERAGE",
        "last_page_bias_trap.INV-PAGE-COVERAGE",
        "cross_platform_duplicate_review.INV-DEDUP",
    }
    print(f"\nall_pass={report['all_pass']} failed={report['failed']}")
    if report["all_pass"]:
        print("PASS: the real candidate passes all 8 invariants on all applicable cases.")
    else:
        newly_failed = set(report["failed"]) - baseline_failed
        print(f"FAIL: candidate does not pass the oracle. Failures: {report['failed']}")
        if newly_failed:
            print(f"New failures not seen even in the naive baseline: {newly_failed}")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
