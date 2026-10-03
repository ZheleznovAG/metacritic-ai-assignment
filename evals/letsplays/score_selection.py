"""Score a let's-play selector's choices against the frozen YTP-02 labels.

A choices file maps each game title to the chosen video id or null. The
metric, acceptance bar and hard invariants are defined in metric.md; this
script only applies them. Without arguments it scores the two reference
baselines on the frozen candidate pool and writes baseline_report.json.

    python evals/letsplays/score_selection.py              # baselines
    python evals/letsplays/score_selection.py choices.json # a candidate
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
MIN_ACCURATE = 17
MAX_FALSE_POSITIVES = 1
HARD_GAME = {"wrong-game", "multi-game", "unconfirmed-game"}
HARD_LANGUAGE = {"letsplay-other-language"}


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def score(choices: dict[str, str | None], labels: dict, pool: dict) -> dict:
    by_title = {game["title"]: game for game in pool["games"]}
    rows, accurate, false_positives, violations = [], 0, 0, []
    for game in labels["games"]:
        title = game["title"]
        if title not in choices:
            raise ValueError(f"no choice for {title}")
        chosen = choices[title]
        known = {item["video_id"]: item["label"] for item in game["labels"]}
        pool_ids = {item["video_id"] for item in by_title[title]["candidates"]}
        if chosen is not None and chosen not in pool_ids:
            violations.append(f"INV-POOL {title}: {chosen}")
        label = known.get(chosen, "unjudged") if chosen else None
        if label in HARD_GAME:
            violations.append(f"INV-GAME {title}: {chosen} is {label}")
        if label in HARD_LANGUAGE:
            violations.append(f"INV-LANGUAGE {title}: {chosen}")
        hit = chosen == game["expected"]
        accurate += hit
        if game["expected"] is None and chosen is not None:
            false_positives += 1
        rows.append(
            {
                "title": title,
                "expected": game["expected"],
                "chosen": chosen,
                "chosen_label": label,
                "hit": hit,
            }
        )
    passed = accurate >= MIN_ACCURATE and false_positives <= MAX_FALSE_POSITIVES and not violations
    return {
        "accurate": accurate,
        "games": len(rows),
        "false_positives": false_positives,
        "violations": violations,
        "passed": passed,
        "rows": rows,
    }


def max_views(game: dict) -> str | None:
    """Reference baseline 1: the most viewed video in the pool."""
    ranked = [item for item in game["candidates"] if item["views"] is not None]
    return ranked[0]["video_id"] if ranked else None


EXCLUDE = re.compile(
    r"\b(trailer|teaser|review|reveal|announcement|soundtrack|ost|shorts?|reaction|"
    r"tier list|news|explained|analysis|guide|tips|no commentary|without commentary)\b",
    re.IGNORECASE,
)


def words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def ytp01_rule(game: dict) -> str | None:
    """Reference baseline 2: the YTP-01 probe filter without its speech check."""
    for item in game["candidates"]:
        if (
            item["views"] is not None
            and words(game["title"]) in words(item["title"])
            and not EXCLUDE.search(item["title"])
            and item["seconds"] >= 600
        ):
            return item["video_id"]
    return None


def main() -> None:
    labels, pool = load("labels.json"), load("candidates.json")
    if len(sys.argv) > 1:
        choices = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        result = score(choices, labels, pool)
        json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
        sys.exit(0 if result["passed"] else 1)
    report = {"labels_version": labels["version"], "baselines": {}}
    for name, selector in (("max-views", max_views), ("ytp01-rule", ytp01_rule)):
        choices = {game["title"]: selector(game) for game in pool["games"]}
        report["baselines"][name] = score(choices, labels, pool)
    target = HERE / "baseline_report.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    for name, result in report["baselines"].items():
        print(
            f"{name}: {result['accurate']}/{result['games']} accurate, "
            f"{result['false_positives']} false positives, "
            f"{len(result['violations'])} violations, passed={result['passed']}"
        )


if __name__ == "__main__":
    main()
