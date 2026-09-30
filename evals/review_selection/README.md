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

## Extension 1.1.0: sentiment coverage

`metric.md` lists sentiment awareness as a non-goal of `1.0.0`. The Likes/Dislikes summary makes it
matter: with 36 positive and 4 negative reviews the `1.0.0-candidate` hash sample selected **0**
negative reviews. The additive extension ([`sentiment_cases.json`](sentiment_cases.json),
[`score_sentiment.py`](score_sentiment.py), `INV-SENTIMENT-COVERAGE`) freezes seven skewed pools and
one hard invariant: at least `min(3, available)` negative and positive reviews are selected. The
`1.0.0` files are untouched and the production selector still passes them.

| Case | available neg/pos | `1.0.0-candidate` selected neg/pos | `1.1.0-sentiment` |
|---|---|---|---|
| skew_positive_few_negatives | 4 / 36 | 0 / 10 (fail) | 3 / 7 |
| skew_negative_few_positives | 27 / 3 | 9 / 1 (fail) | 7 / 3 |
| critic_scale_zero_to_hundred | 2 / 20 | 1 / 7 (fail) | 2 / 6 |
| mostly_unscored | 3 / 3 | 2 / 2 (fail) | 3 / 3 |
| balanced_pool, all_positive_no_negatives, small_pool_no_exclusion | - | pass | pass |

`verify_candidate.py` runs the `1.0.0` oracle and every extension; `test_score_sentiment.py` proves the scorer rejects a
sentiment-blind selector and accepts a balanced reference.

## Extension 1.2.0: meaningful eligibility

The [2026-09-18 audit](../../docs/requirements/main_audit_2026_09_18.md#ma-01-пустые-отзывы-занимают-ai-выборку)
(`MA-01`) showed blank reviews occupying the bounded sample: with 20 blank and 3 meaningful user
reviews only one meaningful review reached the model. The additive extension
([`meaningful_cases.json`](meaningful_cases.json), [`score_meaningful.py`](score_meaningful.py),
`INV-MEANINGFUL-ELIGIBILITY`) freezes seven pools and one hard invariant: the selection holds exactly
`min(10, M)` meaningful reviews, `M` being the pool's distinct meaningful canonical groups. Ground
truth is the authored `meaningful` field. Earlier files are untouched.

| Case | meaningful available | `1.1.0-sentiment` selected |
|---|---|---|
| audit_blank_flood | 3 | 2 (fail) |
| blank_negatives_crowd_reservation | 12 | 8 (fail) |
| one_platform_all_blank | 7 | 5 (fail) |
| critic_scale_blanks | 5 | 3 (fail) |
| whitespace_only_texts | 4 | 3 (fail) |
| all_blank, no_blank_control | 0, 14 | pass |

`test_score_meaningful.py` proves the scorer rejects a blank-blind selector and the naive baseline
and accepts a meaningful-first reference. Before this extension `verify_candidate.py` imported the
`1.1.0` scorer without running it; it now runs every extension against the real candidate.
