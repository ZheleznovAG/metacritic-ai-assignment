# ADR-0003: Text-hybrid similarity policy for the running service

- **Status:** Implemented for the personal service, 2026-09-21. Not a formal re-run of the
  `IMP-06`/`SIM-VER-01` gates; owner acceptance is recorded only in
  [action_plan.md](../../action_plan.md).
- **Supersedes:** [ADR-0002](0002-genre-similarity-policy.md) and `ASM-21` for the running service.
  The delivered baseline (`genre-jaccard` 1.0.0, its frozen synthetic oracle and comparison) is kept
  unchanged as evidence and as the comparison baseline.
- **Requirements/risks:** `SIM-01`, `SIM-02`, `AC-SIM-01/02/03`, `ASM-20/21`, `R-SIM-01`.

## Context

Against the real catalogue (829 games) the source labels each game with one genre out of 83. Genre
Jaccard is therefore 1 or 0 and results inside a genre fall back to the alphabet, so "similar
games" were the first five games of the same genre by title. The frozen 14-case oracle could not
show this: its synthetic games have several genres and no text.

## Decision

Use policy `text-hybrid` 2.0.0 ([`similarity/text.py`](../../app/similarity/text.py)): sentence
embedding (`sentence-transformers/all-MiniLM-L6-v2`, ONNX via `fastembed`) plus TF-IDF over title,
genre and description, fused per query by z-score, floor `3.5`, at most five results. Ranking is
precomputed by the worker (`catalog.similarity_index`) and only read by the web role.

## Evidence

[`evals/similarity/text_labels.json`](../../evals/similarity/text_labels.json) holds 11 queries
(seeded random sample) and 83 graded candidates; [`text_report.json`](../../evals/similarity/text_report.json)
is produced by [`score_text.py`](../../evals/similarity/score_text.py) with the real model.

| Method | nDCG@5 | precision | results/query |
|---|---|---|---|
| `genre-jaccard` 1.0.0 | 0.193 | 0.28 | 4.27 |
| `text-hybrid` 2.0.0 | 0.711 | 0.65 | 4.36 |

Exploration before the choice (same labels, linear gain, before the floor): TF-IDF 0.47, bge-small
0.53, MiniLM 0.48, two-model ensemble 0.56, one model + TF-IDF 0.63-0.68, two models + TF-IDF 0.72.
The single-model hybrid was chosen for size and simplicity; the differences among hybrids are inside
the noise of 11 queries. The floor `3.5` cost 0.013 nDCG for +0.07 precision; `4.0` cost 0.09.

## Limitations (disclosed, not resolved)

- **Post-hoc protocol.** The AGENTS.md rule to freeze examples, metric and threshold before choosing
  a method was not followed: the sample was drawn first, but candidates were graded with the
  proposing methods visible, the floor was tuned on the same labels and the acceptance bar
  (`text-hybrid` beats the baseline by more than 0.3 nDCG) was set after the numbers were known.
- **One grader, 11 queries.** The grader is the assistant. Confidence intervals are wide; only the
  gap to genre Jaccard (0.19 vs 0.71) is large enough to be trusted.
- **Unlabelled results count as grade 0**, which understates methods that return games outside the
  candidate pool.
- **Noisy catalogue.** Many listings are legacy mobile apps whose description does not match the
  title (verified on live pages: it is Metacritic's data). Scores of such games say little about
  their titles.
- **English model.** `all-MiniLM-L6-v2` is English-only; non-English descriptions rank poorly.
- **Cost.** +414 MB image, larger worker memory limit, O(N^2) rebuild.

## Rollback

The web reads `game_neighbors` only. To go back, restore `list_similar_games()` to rank
`similarity.policy` over `Game.genres` (the module and its tests are unchanged) and drop the worker
call in `run_worker._maintain_similar_games`; the two tables can stay unused.
