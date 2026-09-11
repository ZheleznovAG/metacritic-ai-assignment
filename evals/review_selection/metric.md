# Review-selection oracle `1.0.0`

`REV-EVAL-01`. Freezes the metric, threshold and hard invariants a candidate bounded-review
selector must satisfy before `IMP-04` compares it against [`baseline_naive.py`](baseline_naive.py)
on the frozen [`cases.json`](cases.json). This oracle is authored from already-accepted design
facts — `ASM-16`'s candidate `1.0.0` selection policy, `ASM-17`'s meaningful-review threshold,
`ASM-19`'s regeneration-on-change contract, and `SPK-02`'s pagination completeness contract
([`reviews-pagination.json`](../../research/feasibility/fixtures/metacritic/reviews-pagination.json))
— not from `IMP-04`'s not-yet-written code, and no candidate implementation exists yet.

## Why invariants, not a rubric

`evals/reviews/rubric.md` scores subjective LLM output quality on a 0/1/2 scale because partial
credit is meaningful there (a summary can be *mostly* grounded). Review selection is deterministic
code behaviour: a selector either includes a duplicate review twice or it does not; there is no
legitimate partial credit for that. This oracle is therefore a set of binary, per-case
`pass`/`fail`/`n/a` invariants, closer in spirit to `SPK-04`'s `PS-INV-01..10` than to the summary
rubric.

## Selector interface under test

[`contract.py`](contract.py) freezes the calling convention: a selector is any
`(SelectionPool) -> SelectionResult` callable. `SelectionPool.collection_status` must be
`"complete"` before a selector may return a result — ASM-16 requires the collection route to reach
"complete/empty snapshot" first; a selector given a `"partial"` pool must raise
`IncompleteCollectionError` instead of silently sampling it.

## Hard invariants

Every invariant is `pass`, `fail`, or `n/a` (not applicable to that case, excluded from the
threshold). A case-level `fail` on any applicable invariant fails that case.

| Code | Checks | Grounded in |
|---|---|---|
| `INV-COMPLETE` | A `collection_status != "complete"` pool makes the selector raise `IncompleteCollectionError`, never return a result | `ASM-16` complete/empty snapshot requirement |
| `INV-CAP` | `len(selected) <= 10`; every selected review's recounted `o200k_harmony` token count is `<= 450` | `ASM-16` candidate `1.0.0`; `research/feasibility/ai-summary.md` token-aware production boundary |
| `INV-DEDUP` | No two selected reviews share a duplicate-content canonical group (`duplicate_of`) | `ASM-16` cross-platform dedupe |
| `INV-PAGE-COVERAGE` | For cases that declare `must_include_at_least_one_of`, the selection intersects that list | `ASM-16` "does not depend on the first page"; required scenario category (first/last-page bias) |
| `INV-DETERMINISM` | Three calls on an unchanged pool return byte-identical ordered selections | `ASM-19` cache/fingerprint semantics require a stable selection for a stable pool |
| `INV-CONTENT-INDEPENDENCE` | Editing any single review's text (identity/platform/page/score unchanged) never changes the *set* of selected identity keys. `n/a` when the pool size is `<= 10`: with nothing to exclude, every selector selects everyone regardless of content, and a `pass` would be vacuous | Required scenario category ("изменение отзыва вне sample"); supports `ASM-19`: a fingerprint keyed on pool membership must not be perturbed by content the selector wouldn't have chosen differently anyway |
| `INV-NO-FABRICATION` | Every selected `identity_key` exists in the input pool; untruncated text is byte-identical to the source; truncated text is an exact token-boundary decode of the source (never a rewrite) | `ASM-16` full text preserved; `PLN-02`/`SPK-05` token-boundary truncation mechanics |
| `INV-MEANINGFUL-COUNT` | `SelectionResult.meaningful_pool_count`/`total_pool_count` match the pool's authored ground truth exactly | `ASM-17` needs an accurate meaningful-review count to decide `insufficient_data`; selection must pass it through faithfully, not decide it |

## Explicit non-goals (observational, not scored)

`cases.json` includes `sentiment_skew_and_rare_topic` because the task's required scenario coverage
names sentiment skew and rare topics explicitly. `ASM-16`'s accepted policy selects by identity hash
and cross-platform round-robin — it is not content- or sentiment-aware, and this oracle does not
invent a representativeness requirement `ASM-16` never asked for. The scorer/case record
`observational` fields (e.g. `rare_topic_review_id`) for transparency, but they never gate
`pass`/`fail`. Making selection content-aware would need a fresh `ASM-16` decision, not an
`REV-EVAL-01` invariant.

## Threshold

A selector **passes** the oracle iff every applicable invariant is `pass` for every case in
`cases.json`. There is no percentage; one `fail` on an applicable invariant means the oracle does
not accept the selector.

[`baseline_naive.py`](baseline_naive.py) is **expected** to fail exactly three invariant instances
— `first_page_bias_trap.INV-PAGE-COVERAGE`, `last_page_bias_trap.INV-PAGE-COVERAGE`,
`cross_platform_duplicate_review.INV-DEDUP` — and pass everything else. This is recorded in the
committed [`baseline_report.json`](baseline_report.json) and demonstrates the oracle has real
discriminative power (a naive but reasonable-looking approach is correctly rejected) before any
real candidate exists. `IMP-04`'s candidate must pass the full oracle with zero failures; if it
cannot, `ASM-16`'s candidate policy needs revisiting before implementation is accepted, not this
oracle.

## Decision categories

Same vocabulary as `evals/reviews/rubric.md`:

- `Proceed` — the candidate selector passes the full oracle.
- `Replan` — the candidate fails one or more invariants; revise the selection policy (not this
  oracle) and re-run against the same frozen `cases.json`.
- `Blocked / Ask` — the oracle itself (this document, `cases.json`, or the interface in
  `contract.py`) needs an owner decision before `IMP-04` can rely on it. This is the current state:
  see the acceptance question in
  [`docs/requirements/rev_eval_01_review.md`](../../docs/requirements/rev_eval_01_review.md).

## Versioning

`cases.json` (`eval_set_version`), `contract.py`, and this document are frozen together. Changing
any of them after acceptance creates version `1.1.0`+ and invalidates any prior "passed" claim
against `1.0.0`, exactly as `evals/reviews/rubric.md`'s versioning rule. The author (this session)
did not see or write any `IMP-04` candidate code before freezing this set — there is none yet.

## Reproduction

See [`README.md`](README.md).
