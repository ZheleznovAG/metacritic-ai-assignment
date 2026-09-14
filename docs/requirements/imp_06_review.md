# IMP-06: similarity comparison and stored genre features

Task `IMP-06`; requirements `SIM-01`, `AC-SIM-01/03`, `DATA-02`; risks
`R-SIM-01`, `R-DAT-01`; assumptions `ASM-20/21`. Current task and gate status
belongs only to [action_plan.md](../../action_plan.md).

## Scope and independent evidence

[ADR-0002](../decisions/0002-genre-similarity-policy.md) records the selection of
`genre-jaccard` 1.0.0. The [comparison report](../../evals/similarity/comparison_report.json)
contains both policies' results for every case, all eight invariants, oracle
version/hash manifest and implementation hashes. The original frozen files and
owner-approved thresholds are unchanged. Genre-only achieved mean and minimum
positive-case nDCG@5 of 1.0; the weighted design candidate violated non-match
exclusions in four cases despite passing the numerical relevance thresholds.

The selected method is in `app/similarity/policy.py`; the rejected method remains
research code in `evals/similarity/candidates.py`. The production module accepts
immutable saved features and returns IDs, scores, shared labels and policy
identity. It cannot read labels or silently obtain features from a live source.

`GameDTO.genres` now carries the page's JSON-LD `VideoGame.genre`. The existing
independent [source fixture](../../app/tests/fixtures/metacritic/elden_ring_detail.min.html)
has the literal `Action RPG` before this implementation. The parser accepts a
string or an array of strings, collapses whitespace and rejects malformed types,
NUL or labels over 255 characters. Array/absence/malformed shapes are defensive
synthetic cases, not additional live observations. Parser contract is `1.1.0`.

Ingestion casefolds and deduplicates labels in source order into `Game.genres`.
`genres_last_changed_fetch` moves only when nonempty genres are accepted. Missing
or empty genres, identity-only discovery and invalid DTOs preserve known values
and their original source. The additive migration initializes legacy rows with
unknown genres and no provenance; subsequent normal ingestion fills them.

| Exit criterion / boundary | Independent check |
|---|---|
| Frozen comparison of both methods | `evals/similarity/compare.py` recomputes both against the frozen evaluator and compares every result/hash to the published report |
| Simplest passing policy and version | Full per-case comparison, first measurement without tuning; constants and structured outputs in production code |
| Deterministic cap, identity and exclusion behavior | `test_similarity_policy.py`: input permutations, duplicate IDs, title ties, conflicting identities, missing query/genres, null metadata and unused-feature changes |
| Source → DTO → storage | `test_catalog_genres.py`: independent real fixture genre, parser types/bounds, canonical storage and source pointer |
| Partial/invalid source does not overwrite good genres | Missing/empty DTO and identity refresh preserve the prior field/source; invalid DTOs retain values and record invalid fetch evidence |
| Existing data survives migration | Populated PostgreSQL migration down/up preserves game ID, core fields and platform relation, without fabricated genres |

## Adversarial review

Self-review covered requirements, acceptance thresholds and hard exclusions,
`R-SIM-01`/`R-DAT-01`, feature availability, source provenance, empty values,
normalization, score ties, duplicate and conflicting IDs, snapshot immutability,
oracle leakage, migration behavior and CI packaging. The weighted candidate's
grade-0 outputs were treated as rejection, not averaged away. No separate agent
or independent reviewer was used.

The source and ranking paths use one label-normalization function. Tests prove
that duplicate/blank genres do not inflate Jaccard, same developer/platform/title
cannot admit unrelated games, and same-title saved IDs remain distinct. Source
absence cannot falsely move genre provenance to a newer fetch. Migration testing
uses a disposable checks database, never the application database.

## Verification and remaining ownership

```powershell
.\.venv-app\Scripts\python.exe -B evals/similarity/score_similarity.py --verify
.\.venv-app\Scripts\python.exe -B evals/similarity/compare.py
.\.venv-app\Scripts\python.exe -B scripts/check.py
```

The comparison command is part of `scripts/check.py`, so the existing Linux/CI
checks image runs the same reproduction without network or AI calls. Use
`compare.py --write` only when deliberately publishing a reviewed new comparison;
normal verification refuses any changed result or source hash.

Local `scripts/check.py` passed: **284 application tests** (18 added), Ruff
format/lint, strict mypy on 107 source files, Django checks, migration drift,
static collection, six scripts tests, 18 planning tests, seven AI-integrity tests,
nine review-selection tests and 14 similarity evaluator tests. Frozen baseline,
production review-selection and similarity comparison verifiers all passed.
[Verification excerpts](../evidence/imp-06-verification.txt) record the run.
Candidate commit: `813c5d0afb68ae60d09afad660332d8bf4163057`.
The owner explicitly authorized pushing this candidate and its subsequent CI
evidence commit to `ZheleznovAG/metacritic-ai-assignment`, branch `main`.
[Hosted CI 34867974090](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34867974090)
passed on the exact candidate SHA above, completing at 2026-09-14 16:22:17 UTC.
Its Linux/PostgreSQL 16 run passed all 284 application tests, the unchanged frozen
comparison, locked image build, offline runtime tokenization, Compose validation,
migrations and runtime startup through Caddy, image identity and HTTP/CSS smoke.
Current task and gate disposition remains in `action_plan.md`.
`SIM-VER-01` owns the DB-to-ranker query, card integration, ID navigation and
public deployment/genre refresh. No UI change, live source/provider call or
application/VDS migration is claimed by this cycle. Existing application databases
must run migration `catalog.0006` before starting updated application code.
