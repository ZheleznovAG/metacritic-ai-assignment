# ADR-0002: Genre Jaccard similarity policy

- **Status:** Accepted — frozen comparison and application verification
- **Task:** `IMP-06`
- **Verification:** [IMP-06 review](../requirements/imp_06_review.md)
- **Requirements/risks:** `SIM-01`, `AC-SIM-01/03`, `ASM-20/21`, `R-SIM-01`
- **Oracle:** accepted `SIM-EVAL-01` 1.0.0; current task status is in [action_plan.md](../../action_plan.md).

## Decision

Select `genre-jaccard` version `1.0.0`, implemented in
[similarity/policy.py](../../app/similarity/policy.py). A pair is eligible only
when its normalized, nonempty genre sets intersect. Its score is the intersection
size divided by the union size. Sort by decreasing score, then casefolded title
and saved integer ID; return at most five distinct saved IDs, excluding the query.
Missing query or missing genres produces no recommendations. Empty feature sets
do not constitute a match. No result is added merely to fill five slots.

Genre normalization collapses whitespace and casefolds whole labels, without
translation, token splitting, inferred parent genres or synonyms. Duplicate labels
do not add weight. The result carries the score, shared genre labels, policy ID
and version. Platforms and developer are present in the saved-feature boundary
but do not affect this policy. The ranker receives one immutable catalog snapshot;
it performs no ORM, HTTP or provider calls. Repeated identical saved rows are
deduplicated; conflicting records for one ID and invalid saved IDs are rejected.

## Comparison evidence

The [reproducible report](../../evals/similarity/comparison_report.json) evaluates
both methods on the unchanged 14-case oracle (nine positive and five empty or
negative scenarios), using all five input-order/repeat probes per case:

| Method | Mean nDCG@5 | Minimum positive case | All hard invariants | Selection |
|---|---|---|---|---|
| Design candidate `weighted-metadata` 0.1.0 | 0.9985716844686247 | 0.9871451602176229 | Fail: grade-0 recommendations in four cases | Rejected |
| Simpler `genre-jaccard` 1.0.0 | 1.0 | 1.0 | Pass in every case and input order | Selected |

The candidate's original `0.60/0.25/0.15` weights, same-developer eligibility and
`>= 0.15` cutoff were retained for the comparison. It returns games from unrelated
genres because they share a developer, failing `action_role_playing`, `racing`,
`developer_trap` and `normalized_metadata`. Its high mean cannot override the
hard exclusions. The genre-only baseline passed on its first measurement; no
weights, labels, acceptance thresholds or case-specific exceptions were tuned.

The ranker adapter receives only saved game features and query ID; judgments and
case names remain inside the frozen evaluator. Production code does not import
the evaluation tree. The report pins the original oracle manifest and hashes
of both implementations, their adapter and comparison command.

## Consequences and boundaries

`Game.genres` and its per-field source pointer are populated only by accepted
detail ingestion. The existing independently captured Elden Ring JSON-LD fixture
contains `genre: "Action RPG"`; the prior application ignored this field.
Migration `catalog.0006_game_genres` preserves existing rows and starts their
genres as unknown (`[]`), with no invented backfill. A successful later detail
fetch supplies the features. Missing/empty source values preserve prior known
genres and their provenance; valid new labels replace the previous set.

This small synthetic set establishes the agreed metadata behavior, not real user
satisfaction, synonym matching or large-catalog capacity. Broad shared labels can
still yield weak real-world matches, and retained source metadata can age. An
unknown genre intentionally prevents recommendations until source data arrives.
The database-to-ranker adapter, card rendering/navigation and public validation
belong to `SIM-VER-01`. This decision neither integrates the UI nor closes G4.
