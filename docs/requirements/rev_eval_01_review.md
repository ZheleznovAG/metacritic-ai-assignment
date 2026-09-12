# REV-EVAL-01: bounded review-selection oracle

Date: 2026-09-11 (UTC). Task `REV-EVAL-01`; type Evaluation design; needed-by `G4`, before `IMP-04`.

**Status: `Verified`.** The owner accepted the oracle as frozen on 2026-09-12: `cases.json` `1.0.0`,
`metric.md` `1.0.0`, and the `contract.py` selector interface are the acceptance bar `IMP-04`'s real
review-selection candidate must pass, compared against `baseline_naive.py`. See the "Ask" section
below for the exact question asked. `IMP-04` is unblocked on this dependency (it still depends on
`IMP-03`, already `Verified`).

## What this freezes

`IMP-04` must select a bounded sample (at most 10 reviews, at most 450 `o200k_harmony` tokens each)
out of a potentially much larger, multi-page, multi-platform review corpus per audience, per
`ASM-16`'s already-accepted candidate `1.0.0` policy (hash-sort within platform, cross-platform
round-robin, cross-platform dedupe). `IMP-04`'s own exit criteria say its candidate selection "must
be compared against a simple baseline on the accepted `REV-EVAL-01`" — this task builds that
baseline and the acceptance oracle, before any `IMP-04` code exists.

Deliverables, all under [`evals/review_selection/`](../../evals/review_selection/):

- [`contract.py`](../../evals/review_selection/contract.py) — the frozen `(SelectionPool) ->
  SelectionResult` interface a candidate selector must implement, plus the shared
  `o200k_harmony` token-counting/truncation helpers (reusing the exact mechanics
  `evals/reviews/check_token_budget.py` already froze for `PLN-02`/`SPK-05`).
- [`cases.json`](../../evals/review_selection/cases.json) `1.0.0` — 8 synthetic full-corpus cases
  covering every category the task requires: multiple pages/platforms, first-page bias, last-page
  bias, sentiment skew, a rare topic, cross-platform duplicates, long text requiring token-boundary
  truncation, a seven-language multilingual mix, and content-independence (the "review changed outside
  the sample" scenario). All review text is project-authored synthetic data, built independently of
  any selection implementation — none exists yet.
- [`metric.md`](../../evals/review_selection/metric.md) `1.0.0` — 8 hard, binary invariants
  (`INV-COMPLETE`, `INV-CAP`, `INV-DEDUP`, `INV-PAGE-COVERAGE`, `INV-DETERMINISM`,
  `INV-CONTENT-INDEPENDENCE`, `INV-NO-FABRICATION`, `INV-MEANINGFUL-COUNT`), each grounded in
  `ASM-16`/`ASM-17`/`ASM-19` or `SPK-02`'s pagination contract, plus an explicit non-goals section
  (sentiment/rare-topic representativeness is observational only — `ASM-16`'s hash-based policy was
  never asked to be content-aware, and this oracle does not invent that requirement). Threshold:
  every applicable invariant must pass for every case; no percentage, since these are binary
  correctness properties, not graded quality.
- [`baseline_naive.py`](../../evals/review_selection/baseline_naive.py) — the required "simple
  baseline": raw fetch-order concatenation, no dedup, no interleaving. Deliberately naive.
- [`score_selection.py`](../../evals/review_selection/score_selection.py) +
  [`test_score_selection.py`](../../evals/review_selection/test_score_selection.py) — the automated
  scorer, and 9 meta-tests proving the scorer itself catches each invariant violation (a selector
  that over-selects, ignores dedup, fabricates a review, lies about counts, ignores
  `collection_status`, or depends selection order on content) rather than trivially passing anything.

## Why the oracle has real teeth, not just a checklist

[`baseline_report.json`](../../evals/review_selection/baseline_report.json) is the committed,
`--verify`-able result of running `score_selection.py` against `baseline_naive.py`. It is **not**
all-green: the naive baseline fails exactly three invariant instances —

- `first_page_bias_trap.INV-PAGE-COVERAGE` and `last_page_bias_trap.INV-PAGE-COVERAGE`: raw
  fetch-order concatenation never reaches the pages holding the pool's only distinctive content;
- `cross_platform_duplicate_review.INV-DEDUP`: it selects the same syndicated critic review twice
  under two platform routes.

Every other invariant passes for the baseline. `INV-DETERMINISM`/`INV-CONTENT-INDEPENDENCE` pass for
the naive baseline by construction, not by luck: its sort key (`platform_slug`, `page_offset`) never
reads review content, so those two invariants say more about the oracle correctly recognising a
content-independent algorithm than about the baseline being close to correct. The three real
failures are specifically the ones `ASM-16`'s real policy (hash-sort + round-robin + dedupe) exists
to fix, and the oracle catches their absence. This is evidence the oracle discriminates a real
defect from a plausible-looking naive implementation before `IMP-04` writes a single line of the
real candidate — not evidence that the naive baseline is nearly sufficient.

`INV-CONTENT-INDEPENDENCE` is only a meaningful check where the pool exceeds the 10-review cap (an
actual exclusion decision exists to perturb); `score_selection.py` marks it `n/a` otherwise. Of the
8 cases, 6 have pools larger than the cap and exercise this invariant for real; `n/a` results do not
count toward "passed".

## Explicit scope boundary

This task does not implement `IMP-04`'s real selector, the review parser, the AI adapter, or the
downstream summarisation contract (`SPK-05` already froze that separately). It does not decide
whether `ASM-16`'s specific policy (hash-sort/round-robin) is the *only* acceptable design — a
future candidate that passes all 8 invariants by a different mechanism is equally acceptable; the
oracle tests observable behaviour, not implementation strategy.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r evals\review_selection\requirements.txt
cd evals\review_selection
..\..\.venv\Scripts\python.exe -m unittest discover -s . -p test_*.py -v   # 9/9 meta-tests
..\..\.venv\Scripts\python.exe score_selection.py --verify baseline_report.json
```

Run locally in this session: 9/9 meta-tests passed; the saved baseline report reproduces exactly
(`--verify` reports no recomputation drift). `evals/review_selection/` is intentionally outside
`scripts/check.py`'s automated suite, for the same reason `evals/reviews/check_token_budget.py` is:
it needs `tiktoken`, which is not a core project dependency (see that eval's own precedent in
`research/feasibility/ai-summary.md`'s reproduction section).

## Ask

Per `methodology.md` rule 3, accepting this oracle is an owner decision, not something this session
can self-approve — the task card requires "обязательный Ask с конкретным вопросом о принятии
oracle" before `IMP-04` may rely on it.

**Do you accept the `REV-EVAL-01` oracle as frozen — the 8 cases in `cases.json` `1.0.0`, the 8 hard
invariants and pass-everything threshold in `metric.md` `1.0.0`, and the `contract.py` selector
interface — as the acceptance bar `IMP-04`'s real review-selection candidate must pass (compared
against `baseline_naive.py`), or should something about the scope/invariants/cases change first?**

**Answered 2026-09-12: accepted as frozen, no changes requested.** `IMP-04` is unblocked on this
dependency.
