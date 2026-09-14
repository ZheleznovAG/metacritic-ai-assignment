# IMP-04: review collection and AI summary revalidation

Date: 2026-09-14 (Asia/Novosibirsk). Task `IMP-04`; requirements `AI-01/02/03`,
`NFR-02/03`; risks `R-AI-01/02`, `R-TIM-02`. Current task/gate statuses belong
only to [action_plan.md](../../action_plan.md). This cycle revalidates review
collection and AI summaries after the ownership/quota/grounding/dual-queue
corrections ([implementation_corrections_batch.md](implementation_corrections_batch.md),
`R01/R07/R08/R09/R10/R11/R13/R14/R18`), none of which had been exercised
against the real site and a real Groq call since they were built and tested
against fake gateways only. Groq is used only within its free-tier limits, per
standing project policy; this cycle made exactly one real model call.

## Local suite before any live call

`python -B scripts/check.py`: 265 application tests (including the 265th from
the same-day `IMP-03` cycle), format/lint/mypy/migration-drift and
frozen/candidate verifiers all green, before any live review/AI call.

## Live run: `scripts/run_worker.py`, dedicated `WORKER_DB_USER` role

The local dev DB already held a 333-row `ReviewCollectionJob` backlog created
automatically by the day's `IMP-03` scheduler ticks (60 catalogued games).
Bounded batches of `--once` ticks (real HTTP to `backend.metacritic.com`, real
DB writes, no fault injection) were run to revalidate the mechanism against
live data, not to clear the whole backlog:

- **R08/R11 durable page retry** confirmed directly: Elden Ring's PC-user
  review job (2,642 real reviews, `id=4`) advanced cleanly across 53 real
  pages to completion, each page's `SourceFetch`/cursor committed durably
  before the next request, matching the corrected per-page attempt-budget
  design.
- **A real, previously-undiscovered site fact, found live, closed before
  commit:** Elden Ring's Xbox-Series-X user-review job (`id=8`) hit the exact
  same offset (`?offset=150`) five times with a genuine `200` response each
  time, exhausting its automatic retry attempts and landing in `retryable`.
  Direct independent re-fetch and parse of that exact URL (outside the
  application) reproduced the failure: `Review item is missing quote text`.
  The response's `data.items` contained a real review
  (`id=038fac3e-3617-4101-b11c-daa7633f0e9e`, score 6, author `"Hulsee"`) with
  `"quote": null` — a genuine score-only user review with no written text at
  all, not a malformed or corrupted field. `_parse_review_item` required
  `quote` to be a string and raised on anything else, including this real
  `null`.

  Fix (`app/metacritic/parser.py`): a `null` (or absent) `quote` is now
  accepted as an empty-text review (`text=""`), matching this project's
  established "natural absence is not an error" convention already used for
  Metascore/Userscore/date/id; any other non-string `quote` (a number, object,
  etc.) still raises. Re-verified live immediately after the fix: the exact
  failing URL now parses cleanly (50 items). The existing
  `test_item_missing_quote_raises` unit test asserted the old (incorrect)
  behavior on a *fabricated* input shaped like this real one; it was replaced
  with `test_item_missing_or_null_quote_is_a_real_score_only_review_not_an_error`
  (using the real observed id/score/author) plus a new
  `test_item_with_a_non_string_quote_raises` guarding the still-rejected
  malformed case. A subsequent live worker tick against the same, now-fixed
  job automatically resumed it from `retryable` back to `pending` and advanced
  past the previously-stuck page with no manual intervention beyond the code
  fix itself — the job's own retry/recovery mechanism (`R08/R11`) did the rest.
- **R01/R07/R09/R10/R13/R14/R18 end-to-end, with one real Groq call:** once
  all five platforms' critic review jobs for Elden Ring reached `complete`,
  the corpus builder atomically built the critic `ReviewCorpus` and created a
  `SummaryJob`, which the same worker process picked up on its very next tick
  (confirming `R14`'s dual-queue fairness live — the worker interleaved
  between a review-collection retry and this summary dispatch without
  starvation) and completed with a **real Groq call**: model
  `openai/gpt-oss-20b`, 1935 prompt tokens, 262 completion tokens, 2197 total,
  1183 ms latency, `outcome=succeeded`, 6 grounded claims, all passing the
  corrected `R07/R13/R18` grounding validator (status `ok`). This is the same
  production Groq account already used by the original `IMP-04` live run and
  stayed within its free-tier limits; no paid tier was used.

`python -B scripts/check.py` after the fix: **266** application tests (265 + 1
net new), everything else unchanged and green.

## Aggregate live evidence

| Metric | Value |
|---|---|
| `review_page` `SourceFetch` rows this cycle | 125 (123 succeeded, 2 invalid — both from before the fix, retained as history) |
| `ReviewCollectionJob` reaching `complete` this cycle | 9 (all 5 Elden Ring critic platforms + 4 of 5 user platforms) |
| New `ReviewCorpus` built | 1 (Elden Ring, critic) |
| New `SummaryJob` created and completed | 1 (Elden Ring, critic) |
| Real Groq calls made | 1 (`succeeded`, grounded, 6 claims) |
| Catalog total after this session's `IMP-03`+`IMP-04` cycles | 60 games, 114 platforms, 3 total succeeded summary jobs (2 pre-existing from the original `IMP-04` review + this cycle's 1) |

## Adversarial review

Reviewed the fix against the same file's other three "non-string raises" guards
(`id`, `date`, and the unchanged `_extract_user_score` from the same-day
`IMP-03` cycle) for a consistent "natural absence vs. malformed" line: `None`
is accepted only where a real natural-absence case was independently observed
live (Metascore/Userscore/date/id already had one from earlier cycles; quote
now has this cycle's `Hulsee` review); any other type still raises rather than
being silently coerced. Checked that an empty-text review does not special-case
anywhere else in the corpus/selection/summary pipeline — `ReviewRecordDTO.text`
already flows into `Review.text_original`/`content_sha256`/`version_sha256`
identically for any string value, and the frozen `REV-EVAL-01` selection
oracle already treats review length as a per-case field with no lower bound.
Checked that this fix does not touch `validate_userscore`/`validate_metascore`,
`_require_matching_review_route`, or the `R01/R09/R10` quota/admission path.
`ruff format`/`ruff check`/`mypy --strict` all pass on the changed files.

## Boundaries and remaining scope

This cycle deliberately did not clear the full 333-job backlog (not the goal
of a revalidation) or attempt a second real Groq call once the first
confirmed the end-to-end path; per project policy, Groq usage stays within
free-tier limits and accumulates/catches up over time rather than forcing
more calls. `HRD-01/04`'s broader failure-taxonomy and capacity evidence,
`PUB-01/02`'s permanent public worker deployment, and `IMP-05/06`'s own
revalidation remain separate, later tasks.
