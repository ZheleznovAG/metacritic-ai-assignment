# REV-EVAL-01: review-selection oracle

Frozen synthetic dataset and hard-invariant scorer for the bounded review-selection step `IMP-04`
implements in `app/reviews/selection.py` (which reviews, out of a full collected corpus, get sent
to the AI summariser). See [`metric.md`](metric.md) for the invariants/threshold and
[`docs/requirements/rev_eval_01_review.md`](../../docs/requirements/rev_eval_01_review.md) for the
decision record and acceptance question (accepted 2026-09-12).

No network access or provider credentials are needed; this is pure local computation. `tiktoken`
became a core project dependency in `IMP-04` (the production selection algorithm itself needs the
real `o200k_harmony` token cap, not a character-count proxy), so this directory's checks now run in
`scripts/check.py`'s automated suite — no separate install step.

## Reproduction

```powershell
cd evals\review_selection
..\..\.venv\Scripts\python.exe -m unittest discover -s . -p test_*.py -v
..\..\.venv\Scripts\python.exe score_selection.py                                   # naive baseline, prints the full report
..\..\.venv\Scripts\python.exe score_selection.py --verify baseline_report.json     # re-check the committed evidence, no writes
```

To evaluate the real `IMP-04` candidate (`app/reviews/selection.py`):

```powershell
$env:PYTHONPATH = "..\..\app"
..\..\.venv\Scripts\python.exe verify_candidate.py
```

`verify_candidate.py` adapts between this eval's frozen `contract.py` dataclasses and
`reviews/selection.py`'s field-identical ones — it does not modify `contract.py`/`cases.json`/
`metric.md`/`score_selection.py`/`baseline_naive.py`. Expected result: 8/8 invariants pass (the
naive baseline in `baseline_report.json` passes only 5/8 — see `metric.md`'s "Threshold" section).

To evaluate any other candidate, implement `(SelectionPool) -> SelectionResult` per
[`contract.py`](contract.py), then:

```powershell
..\..\.venv\Scripts\python.exe score_selection.py --selector some.module:select_reviews
```
