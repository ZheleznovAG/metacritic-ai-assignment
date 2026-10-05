# Research freeze and independent-holdout boundary

FIN-RESEARCH, 2026-10-05, baseline `500305a`. This is a research contract, not a
task tracker; decisions and dependencies remain in [action_plan.md](../action_plan.md).
Requirement/risk mappings: `SIM-01–03`, `YT-01`, `AC-YT-04/05`, `R-SIM-01`,
`R-BON-YT-02`, `R-TST-01`.

## Freeze decision and stop rule

Keep `text-hybrid` 3.0.0, `letsplay-select` 1.0.0 and `letsplay-conclusion` 2.1.0.
Keep Let's Play experimental with the existing visible attribution warning.
Existing owner decisions [ADR-0004](decisions/0004-foreign-description-gate.md) and
[ADR-0006](decisions/0006-letsplay-conclusion-accepted-with-limitation.md) accept
specific unmet criteria; this cycle adds no acceptance waiver.

The [freeze manifest](evidence/fin-research/freeze.json) pins policy/evaluation code,
prompts/schemas, model/dependency identity, labels, metrics and reports by SHA-256.
Do not tune on these sets again, relabel failures to improve the score, lower a
threshold or call them holdout. Earlier failed candidates and corrections remain.
An intentional future change needs a new version, reviewed manifest and separately
preregistered evidence. Existing versions stop here; research does not block final
packaging under the existing accepted limitations.

## What the evidence establishes

| Subsystem | Recorded result | Claim boundary |
|---|---|---|
| Similarity set 2.0.0, 24 queries | current nDCG@5 0.570, precision 0.508; genre baseline 0.382/0.472; previous hybrid 0.318/0.343 | Grading was pooled/blind to method, but detector/genre bonus were tuned on this set; it is development evidence |
| Similarity set 1.0.0, 11 queries | previous hybrid 0.605 → current 0.378; allowed drop 0.03, observed 0.227 | Frozen criterion 3 fails; conflicting identities explain some cases, not independent proof that the regression is harmless |
| Similarity coverage | 1196/1196 versus previous 1046/1196 on saved snapshot | Coverage means any result, not relevant results; 27/120 set-2 results are unjudged and count as zero |
| Let's Play selection, 20 games | 18/20, zero false positives or recorded invariant violations | Parameters tuned on this pool; “most popular” only within saved candidates, not all of YouTube |
| Let's Play conclusion, 14 cases | structural checks 14/14; semantic 111/132 (84.1%), one blocking LP-04 error | 85% and mandatory grounding/disclosure criteria are unmet; verbatim segments do not establish correct attribution |

Original protocols: [similarity](../evals/similarity/text_comparison_v2.md),
[Let's Play metric](../evals/letsplays/metric.md),
[conclusion grades/results](../evals/letsplays/conclusion_results.md).
One AI grader and reused development examples cannot establish independent quality.
No independent holdout has been collected, graded or passed in this cycle.

The fresh Linux real-model [replay](evidence/fin-research/similarity_replay.json)
does **not** exactly reproduce the historical report. Set-2 current nDCG/precision
is 0.548/0.492, previous hybrid 0.294/0.314; current set-1 is 0.378 versus previous
0.569. Coverage is 1196 versus previous 1045. The current method still has the
disclosed cross-set regression and no independent quality evidence. The cause of
the replay drift is not established; historical model binary/environment hashes
were not recorded. The original report remains unchanged, and this cycle pins
the replay model's actual ONNX SHA-256 and snapshot identity. Exact historical
reproducibility is an additional disclosed limitation, not a passed criterion.

Replay verifies original input hashes, policy wiring, report consistency, validation
and unchanged historical grades. It does not rerun stochastic providers, provide a
second semantic grader or measure current catalog/YouTube conditions. Raw snapshots,
transcripts and quoted provider responses remain outside Git.

## Provider budgets and operational limits

The original metric's planning budget for `gpt-oss-20b` is historical. The frozen
conclusion actually uses separate `openai/gpt-oss-120b`, at most 2500 transcript
words, 1200 completion tokens and 5000 reserved request tokens. Runtime ledger
enforces 25 chat calls/day plus token windows; provider refusals override local
counts. These are configured service budgets, not a new verification of current
external provider limits. Relevant [budget source](../app/letsplays/budget.py),
[conclusion source](../app/letsplays/conclusion.py) and tests are pinned.

Saved subtitle inputs can cover up to 15 minutes; the audio fallback covers up to
320 seconds. Historical conclusions on longer inputs do not certify shorter-input
production quality. Captions/IP blocking and search quotas still limit throughput;
no availability or processing-rate SLA is introduced.

## Future similarity holdout protocol (proposed, not executed)

Before viewing outputs, freeze a fresh cleaned snapshot, source/model hashes,
sampling seed, candidate methods, scoring code and grading instructions. A reviewer
independent of tuning validates identity/description agreement; titles alone do
not certify source correctness. Exclude all old labeled query IDs and reuse of old
graded pairs. No automatic/LLM-generated labels count as independent human acceptance.

Use at least 48 queries with predefined strata covering negative/no-relevant cases,
cross-genre relations, remasters/remakes, franchises, sparse descriptions and normal
description-rich games (at least eight per stratum). Record any overlapping stratum
membership and denominator explicitly. Pool fixed top-five outputs from genre,
TF-IDF, embedding, frozen hybrid and current production, plus independent negatives;
blind method/order during grading. Report unjudged pairs separately; publish hashes
and sanitized labels, keeping third-party text outside Git.

Preregister one primary comparison, current production versus genre baseline;
ablations are diagnostic, not a method-selection leaderboard. Proposed acceptance:
mean nDCG@5 improvement ≥0.05, nondecreasing precision/coverage, no stratum drop >0.05,
and all self/duplicate/catalog/max-five/determinism invariants. Report paired 95%
bootstrap uncertainty with fixed seed and 10,000 resamples. Negative/no-relevant
queries remain in false-positive/coverage accounting even when nDCG is undefined.
These proposed thresholds are not retroactive replacements for the original bar.

Score once without tuning. If the frozen current policy meets the approved bar,
stop. If it fails, disclose the failure and keep the accepted limited policy or
begin a separately authorized research cycle with new development data and a new
untouched holdout. This protocol does not claim a holdout exists or is accepted.

## Future Let's Play holdout protocol (proposed, not executed)

Freeze at least 24 new clips/cases, disjoint from the original games/videos, with
at least four each covering UI text, character dialogue, sarcasm, momentary reactions,
silence/non-author speech and genuine author opinions. Include sponsorship disclosure
and both production-length audio and subtitle inputs; freeze exact text hashes and
expected sufficient/insufficient states before any model output is examined.

Use two graders independent of prompt tuning, blind to contour version, with explicit
adjudication of disagreements and evidence for attributed opinions. Keep the existing
rubric: no blocking error, all applicable GROUND/INSUFFICIENT/DISCLOSURE scores 2,
no other zero, aggregate ≥85%. Record results per error class and input length.
Segment validity and budget compliance are hard checks, separate from semantic scores.
Existing negative controls are retained; passing them alone is not a holdout result.

No new contour is selected on these cases. If an independently frozen contour fails
the approved quality bar, keep the feature experimental and stop prompt iteration.
Any new acceptance exception belongs to an explicit owner decision with its actual
failed result. No live provider calls or independent grading occurred for this protocol.
