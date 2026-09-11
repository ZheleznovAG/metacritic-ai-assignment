# REV-EVAL-01: review-selection oracle

Frozen synthetic dataset and hard-invariant scorer for the bounded review-selection step that
`IMP-04` will implement (which reviews, out of a full collected corpus, get sent to the AI
summariser). See [`metric.md`](metric.md) for the invariants/threshold and
[`docs/requirements/rev_eval_01_review.md`](../../docs/requirements/rev_eval_01_review.md) for the
decision record and acceptance question.

No network access or provider credentials are needed; this is pure local computation. It requires
`tiktoken` (not part of the core project dependencies, same as `evals/reviews/check_token_budget.py`)
because the oracle checks the real `o200k_harmony` token cap, not a character-count proxy.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m pip install -r evals\review_selection\requirements.txt
cd evals\review_selection
..\..\.venv\Scripts\python.exe -m unittest discover -s . -p test_*.py -v
..\..\.venv\Scripts\python.exe score_selection.py                                   # naive baseline, prints the full report
..\..\.venv\Scripts\python.exe score_selection.py --verify baseline_report.json     # re-check the committed evidence, no writes
```

To evaluate a real candidate once `IMP-04` exists: implement `(SelectionPool) -> SelectionResult`
per [`contract.py`](contract.py), then:

```powershell
..\..\.venv\Scripts\python.exe score_selection.py --selector some.module:select_reviews
```

`baseline_report.json` is committed evidence from `baseline_naive.py` (a deliberately naive
selector), not from any real candidate — see `metric.md`'s "Threshold" section for the three
invariant failures it is expected to have.

This directory is intentionally outside `scripts/check.py`'s automated suite, for the same reason
`check_token_budget.py` is: it needs `tiktoken`, which is not a core project dependency. Re-run the
commands above locally (or in a dedicated CI step) whenever `cases.json`, `contract.py`, or
`baseline_naive.py` change.
