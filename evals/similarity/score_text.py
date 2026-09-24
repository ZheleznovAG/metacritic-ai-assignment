"""SIM-EVAL-01 extension: score similar-games methods on hand-graded real-catalogue queries.

    PYTHONPATH=app python evals/similarity/score_text.py --snapshot PATH [--write REPORT]

`--snapshot` is a JSON list of `{"source_game_id", "title", "genres": [...], "description"}` rows
exported from the catalogue (see `text_comparison.md`); it is third-party text,
so it stays outside Git and only its SHA-256 goes into the report. Both label sets are scored:
[`text_labels.json`](text_labels.json) (1.0.0) and [`text_labels_v2.json`](text_labels_v2.json)
(2.0.0). Methods compared:

* `genre-jaccard` 1.0.0 - the first production policy (`similarity.policy`);
* `text-hybrid` 2.0.0 - description-only text ranking (`similarity.text.rank_neighbors`);
* `text-hybrid` 3.0.0 - the current policy (`similarity.text.rank`), with the real ONNX model.

Metric (same definition as `metric.md`): nDCG@5 with gain `2^grade - 1` and discount
`log2(rank + 1)`; the denominator is the best possible ranking of the judged candidates. Returned
games without a label count as grade 0; where a set records its candidate pool, returned games
outside it are counted as `unjudged_results`. Also reported: precision (share of returned games
graded 1 or 2), the mean number of results per query and catalogue coverage (games with any result).

`text_report.json` (set 1.0.0 only, 829-game snapshot) was written by the revision of this script
in commit c5ffb97 and is kept as history; `text_report_v2.json` is written by this one.
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
LABEL_SETS = {"1.0.0": LABELS, "2.0.0": HERE / "text_labels_v2.json"}
METHODS = ("genre-jaccard", "text-hybrid@2.0.0", "text-hybrid@3.0.0")


def dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(grades))


def ndcg_at_5(returned: list[str], judged: dict[str, int]) -> float | None:
    ideal = dcg(sorted((g for g in judged.values() if g > 0), reverse=True)[:5])
    if ideal == 0:
        return None
    return dcg([judged.get(game, 0) for game in returned[:5]]) / ideal


def score_method(rankings: dict[str, list[str]], labels: dict[str, Any]) -> dict[str, Any]:
    per_query: dict[str, float | None] = {}
    returned_total = relevant_total = unjudged = 0
    for query in labels["queries"]:
        judged = {game: entry["grade"] for game, entry in query["grades"].items()}
        returned = rankings.get(query["source_game_id"], [])[:5]
        per_query[query["source_game_id"]] = ndcg_at_5(returned, judged)
        returned_total += len(returned)
        relevant_total += sum(1 for game in returned if judged.get(game, 0) >= 1)
        if "pool" in query:
            pool = set(query["pool"])
            unjudged += sum(1 for game in returned if game not in pool)
    scored = [value for value in per_query.values() if value is not None]
    count = len(labels["queries"])
    return {
        "mean_ndcg_at_5": round(sum(scored) / len(scored), 3) if scored else None,
        "precision": round(relevant_total / returned_total, 3) if returned_total else None,
        "mean_results_per_query": round(returned_total / count, 2) if count else None,
        "unjudged_results": unjudged,
        "per_query_ndcg": {
            game: (None if v is None else round(v, 3)) for game, v in per_query.items()
        },
    }


def load_labels(path: Path = LABELS) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _current_items(snapshot: list[dict[str, Any]], by_source: dict[str, int], embedder: Any) -> list:
    """`similarity.text.Item`s for the whole snapshot, embedded exactly as the worker does."""
    from similarity import text as text_policy

    labels = [text_policy.label_text(row["title"], tuple(row["genres"])) for row in snapshot]
    usable = [
        text_policy.description_problem(row["title"], row.get("description")) is None
        for row in snapshot
    ]
    full = [
        text_policy.game_text(row["title"], tuple(row["genres"]), row["description"] or "")
        for row, ok in zip(snapshot, usable, strict=True)
        if ok
    ]
    label_vectors = embedder.embed(labels)
    full_vectors = iter(embedder.embed(full)) if full else iter(())
    full_texts = iter(full)
    return [
        text_policy.Item(
            game_id=by_source[row["source_game_id"]],
            genres=tuple(row["genres"]),
            label_text=label,
            label_vector=vector,
            text=next(full_texts) if ok else None,
            vector=next(full_vectors) if ok else None,
        )
        for row, label, vector, ok in zip(snapshot, labels, label_vectors, usable, strict=True)
    ]


def rank_all(
    snapshot: list[dict[str, Any]], embedder: Any, queries: set[str] | None = None
) -> dict[str, dict[str, list[str]]]:
    """Every method's top results keyed by `source_game_id`.

    The text methods rank the whole snapshot (coverage needs every game); `genre-jaccard` ranks
    only `queries` (default: the queries of label set 1.0.0).
    """
    from similarity import policy as genre_policy
    from similarity import text as text_policy

    by_source = {row["source_game_id"]: index + 1 for index, row in enumerate(snapshot)}
    source_of = {index: source for source, index in by_source.items()}
    if queries is None:
        queries = {q["source_game_id"] for q in load_labels()["queries"]}

    saved = tuple(
        genre_policy.SavedGame(
            id=by_source[row["source_game_id"]], title=row["title"], genres=tuple(row["genres"])
        )
        for row in snapshot
    )
    jaccard = {
        source: [source_of[r.game_id] for r in genre_policy.rank(by_source[source], saved)]
        for source in queries
        if source in by_source
    }

    described = [row for row in snapshot if text_policy.has_signal(row.get("description"))]
    texts = [
        text_policy.game_text(row["title"], tuple(row["genres"]), row["description"])
        for row in described
    ]
    ids = [by_source[row["source_game_id"]] for row in described]
    previous = text_policy.rank_neighbors(ids, texts, embedder.embed(texts))
    current = text_policy.rank(_current_items(snapshot, by_source, embedder))

    def sources(ranked: dict[int, Any]) -> dict[str, list[str]]:
        return {
            source_of[game_id]: [source_of[n.game_id] for n in neighbours]
            for game_id, neighbours in ranked.items()
        }

    return {
        "genre-jaccard": jaccard,
        "text-hybrid@2.0.0": sources(previous),
        "text-hybrid@3.0.0": sources(current),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--write", type=Path, help="write the JSON report to this path")
    arguments = parser.parse_args()

    from similarity import text as text_policy
    from similarity.embedder import FastEmbedder

    raw = arguments.snapshot.read_bytes()
    snapshot = json.loads(raw)
    label_sets = {version: load_labels(path) for version, path in LABEL_SETS.items()}
    known = {row["source_game_id"] for row in snapshot}
    queries = {q["source_game_id"] for s in label_sets.values() for q in s["queries"]}
    if missing := sorted(queries - known):
        print(f"snapshot lacks labelled games: {missing}", file=sys.stderr)
        return 2

    rankings = rank_all(snapshot, FastEmbedder(), queries)
    report = {
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot_games": len(snapshot),
        "described_games": sum(
            1 for row in snapshot if text_policy.has_signal(row.get("description"))
        ),
        "usable_descriptions": sum(
            1
            for row in snapshot
            if text_policy.description_problem(row["title"], row.get("description")) is None
        ),
        "model": text_policy.MODEL_ID,
        "coverage": {
            method: sum(1 for games in rankings[method].values() if games)
            for method in METHODS[1:]
        },
        "sets": {
            version: {
                "labels_sha256": hashlib.sha256(LABEL_SETS[version].read_bytes()).hexdigest(),
                "methods": {
                    method: score_method(rankings[method], labels) for method in METHODS
                },
            }
            for version, labels in label_sets.items()
        },
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if arguments.write:
        arguments.write.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
