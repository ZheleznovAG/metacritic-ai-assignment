# Published `SPK-05` baseline

Task: `PLN-02` evidence correction; requirements `AI-01–AI-03`, `NFR-06`.

This is the saved run of 2026-09-07 (`10:44:49Z–10:46:10Z`), published on 2026-09-08 UTC. It is not a new model run or a new manual evaluation. Inputs are the project-authored synthetic reviews in [`cases.json`](../cases.json).

- [`run.json`](run.json) preserves all fields of the local sanitised run: canonical model outputs, normalisation notes, safe metadata, usage and artifact fingerprints.
- [`scorecard.json`](scorecard.json) preserves the original scores, notes and timestamps. Only `run_artifact` was changed to its repository path; `run_sha256` and `rubric_sha256` were added for read-only verification.
- The original scorecard did not record a reviewer identity (`null`). No identity or independent human review is reconstructed retrospectively.

Original local artifact SHA-256, before publication formatting/path changes:

| Artifact | SHA-256 |
|---|---|
| Sanitised `run.json` | `c224f67fb471e55e7a9494836b83821ba7b5c82a3a0683c6b7c58cb2a5b7fed7` |
| Completed `scorecard.json` | `f8caef9c3ce0e243e611a098a08cba993128538dc6f38afc89c3c52baf66465d` |

No API key, authorization data, provider request ID, raw reasoning or raw response envelope is included. The saved outputs are **after** normalisation: the discarded sixth `contrast_user.likes` item was not archived, so this evidence supports re-evaluation of the canonical output, not reconstruction of the raw response or re-evaluation of that discarded item.

## Offline verification

From the repository root with Python 3.12 or later; no dependencies, `.env` or API credentials are needed:

```powershell
python -B evals/reviews/score_run.py evals/reviews/baseline/run.json --verify
```

The command revalidates all nine saved outputs against their inputs, checks exact case coverage and hashes, recomputes automatic findings and token totals, checks rubric applicability and recalculates `96/98` (`97.96%`) from the original manual scores. It does not independently assign semantic scores. Anyone can inspect the original inputs, outputs and notes to challenge those scores without making another model call. Do not use `--finalize` on this immutable published baseline.

The frozen examples are English and synthetic. The separate multilingual token-boundary check does not establish multilingual summary quality or production capacity.
