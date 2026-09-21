"""SIM-EVAL-01 extension: score similar-games methods on hand-graded real-catalogue queries.

    PYTHONPATH=app python evals/similarity/score_text.py --snapshot PATH [--write REPORT]

`--snapshot` is a JSON list of `{"source_game_id", "title", "genres": [...], "description"}` rows
exported from the catalogue (see `text_comparison.md`); it is third-party text,
so it stays outside Git and only its SHA-256 goes into the report. The labels are
[`text_labels.json`](text_labels.json). Methods compared:

* `genre-jaccard` 1.0.0 - the previous production policy (`similarity.policy`);
* `text-hybrid` 2.0.0 - the current one (`similarity.text` with the real ONNX model).

Metric (same definition as `metric.md`): nDCG@5 with gain `2^grade - 1` and discount
`log2(rank + 1)`; the denominator is the best possible ranking of the judged candidates. Returned
games without a label count as grade 0. Also reported: precision (share of returned games graded
1 or 2) and the mean number of results per query.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LABELS = HERE / "text_labels.json"


def dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades))


def ndcg_at_5(returned: list[str], judged: dict[str, int]) -> float | None:
    ideal = dcg(sorted((g for g in judged.values() if g > 0), reverse=True)[:5])
    if ideal == 0:
        return None
    return dcg([judged.get(game, 0) for game in returned[:5]]) / ideal


def score_method(rankings: dict[str, list[str]], labels: dict[str, Any]) -> dict[str, Any]:
    per_query: dict[str, float | None] = {}
    returned_total = relevant_total = 0
    for query in labels["queries"]:
        judged = {game: entry["grade"] for game, entry in query["grades"].items()}
        returned = rankings.get(query["source_game_id"], [])[:5]
        per_query[query["source_game_id"]] = ndcg_at_5(returned, judged)
        returned_total += len(returned)
        relevant_total += sum(1 for game in returned if judged.get(game, 0) >= 1)
    scored = [value for value in per_query.values() if value is not None]
    count = len(labels["queries"])
    return {
        "mean_ndcg_at_5": round(sum(scored) / len(scored), 3) if scored else None,
        "precision": round(relevant_total / returned_total, 3) if returned_total else None,
        "mean_results_per_query": round(returned_total / count, 2) if count else None,
        "per_query_ndcg": {
            game: (None if v is None else round(v, 3)) for game, v in per_query.items()
        },
    }


def load_labels() -> dict[str, Any]:
    return json.loads(LABELS.read_text(encoding="utf-8"))


def rank_all(snapshot: list[dict[str, Any]], embedder: Any) -> dict[str, dict[str, list[str]]]:
    """Both methods' top results for every labelled query, keyed by `source_game_id`."""
    from similarity import policy as genre_policy
    from similarity import text as text_policy

    by_source = {row["source_game_id"]: index + 1 for index, row in enumerate(snapshot)}
    source_of = {index: source for source, index in by_source.items()}
    labelled = {q["source_game_id"] for q in load_labels()["queries"]}

    saved = tuple(
        genre_policy.SavedGame(
            id=by_source[row["source_game_id"]], title=row["title"], genres=tuple(row["genres"])
        )
        for row in snapshot
    )
    jaccard = {
        source: [source_of[r.game_id] for r in genre_policy.rank(by_source[source], saved)]
        for source in labelled
        if source in by_source
    }

    described = [row for row in snapshot if text_policy.has_signal(row.get("description"))]
    texts = [
        text_policy.game_text(row["title"], tuple(row["genres"]), row["description"])
        for row in described
    ]
    ids = [by_source[row["source_game_id"]] for row in described]
    ranked = text_policy.rank_neighbors(ids, texts, embedder.embed(texts))
    hybrid = {
        source: [source_of[n.game_id] for n in ranked.get(by_source[source], ())]
        for source in labelled
        if source in by_source
    }
    return {"genre-jaccard": jaccard, "text-hybrid": hybrid}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--write", type=Path, help="write the JSON report to this path")
    arguments = parser.parse_args()

    from similarity import policy as genre_policy
    from similarity import text as text_policy
    from similarity.embedder import FastEmbedder

    raw = arguments.snapshot.read_bytes()
    snapshot = json.loads(raw)
    labels = load_labels()
    known = {row["source_game_id"] for row in snapshot}
    missing = [q["source_game_id"] for q in labels["queries"] if q["source_game_id"] not in known]
    if missing:
        print(f"snapshot lacks labelled games: {missing}", file=sys.stderr)
        return 2

    rankings = rank_all(snapshot, FastEmbedder())
    report = {
        "labels_sha256": hashlib.sha256(LABELS.read_bytes()).hexdigest(),
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot_games": len(snapshot),
        "described_games": sum(
            1 for row in snapshot if text_policy.has_signal(row.get("description"))
        ),
        "model": text_policy.MODEL_ID,
        "methods": {
            "genre-jaccard": {
                "version": genre_policy.POLICY_VERSION,
                **score_method(rankings["genre-jaccard"], labels),
            },
            "text-hybrid": {
                "version": text_policy.POLICY_VERSION,
                **score_method(rankings["text-hybrid"], labels),
            },
        },
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if arguments.write:
        arguments.write.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
