"""Apply the frozen conclusion bar (metric.md) to the recorded rubric grades.

The bar: no blocking error; GROUND, INSUFFICIENT and DISCLOSURE are 2 wherever they apply; no
other criterion is 0; the total is at least 85% of the applicable maximum. Structural validity is
checked separately by the contour (conclusion_run_<version>.json).

    python evals/letsplays/score_conclusions.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
CRITERIA = ("GROUND", "ATTRIBUTION", "BALANCE", "INSUFFICIENT", "DISCLOSURE", "FORMAT")
MUST_BE_TWO = ("GROUND", "INSUFFICIENT", "DISCLOSURE")
SHARE = 0.85


def judge(grades: dict[str, dict[str, object]]) -> dict[str, object]:
    total = maximum = 0
    blocking, below_two, zeros = [], [], []
    for case, row in grades.items():
        if "blocking" in row:
            blocking.append(case)
        for criterion in CRITERIA:
            score = row.get(criterion)
            if not isinstance(score, int):
                continue
            total += score
            maximum += 2
            if criterion in MUST_BE_TWO and score < 2:
                below_two.append(f"{case}:{criterion}")
            elif score == 0:
                zeros.append(f"{case}:{criterion}")
    share = total / maximum if maximum else 0.0
    return {
        "total": total,
        "maximum": maximum,
        "share": round(share, 3),
        "blocking": blocking,
        "must_be_two_missed": below_two,
        "zeros": zeros,
        "passed": not blocking and not below_two and not zeros and share >= SHARE,
    }


def main() -> None:
    document = json.loads((HERE / "conclusion_grades.json").read_text(encoding="utf-8"))
    for version, grades in document["runs"].items():
        print(version, json.dumps(judge(grades), ensure_ascii=False))


if __name__ == "__main__":
    main()
