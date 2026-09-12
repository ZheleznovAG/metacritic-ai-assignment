# IMP-04: durable review collection + AI review-summary contour

Date: 2026-09-12 (UTC). Task `IMP-04`; requirements `AI-01`, `AI-02`, `AI-03` (mechanism); risks
`R-AI-01`, `R-AI-02`. Current status belongs to [action_plan.md](../../action_plan.md).

## Scope actually built

The full `docs/design.md` schema for review collection, corpus building, and AI summarization:
`catalog.SourceFetch` extended with review-page attempt evidence (job/generation/page/attempt/
fencing/reported_total/item_count); `reviews` app extended with the real `ReviewCollectionJob`
state machine plus new `Review`/`ReviewObservation`/`ReviewCorpus`/`ReviewCorpusItem` models; a new
`summaries` app (`SummaryJob`/`SummaryAttempt`/`ReviewSummary`/`SummaryClaim`). A real backend
review-page gateway/parser (`metacritic/{dto,parser,gateway}.py`) against
`backend.metacritic.com`'s JSON API. `reviews/selection.py` implements `ASM-16`'s exact candidate
`1.0.0` policy (cross-platform dedup, hash-sort + round-robin, ≤10 reviews capped at 450
`o200k_harmony` tokens each) as a pure function verified against the accepted `REV-EVAL-01` oracle.
`reviews/collector.py` is the row-leased, durable one-page-per-claim collection worker.
`summaries/{contour,groq_adapter,quota,worker,observability}.py` is the production Groq adapter and
job/attempt state machine: real HTTP mechanics, persistent minute/day quota admission (no separate
counter table — the ledger is committed `SummaryAttempt` rows), bounded backoff, cache-hit via
`(game, audience, input_fingerprint, contour_fingerprint)`, and backlog/oldest-age visibility.
`app/reviews/management/commands/run_worker.py` + `scripts/run_worker.py` (new `WORKER_DB_USER`
role) is the real worker entry point, mirroring `IMP-03`'s scheduler pattern. The public card
(`presentation/summaries.py` + `game_detail.html`) shows both audiences' current summary with
honest `pending`/`stale`/`insufficient_data` states and disclosed model/generated-at/coverage
counts — no raw reviews shown.

Explicitly deferred (per the plan's scope boundary): real concurrent-process crash/race stress
testing (`HRD-02`/`HRD-03` — this cycle proves the row-lease/fencing mechanism via controlled
simulation plus real live crash-simulation reclaim tests, not adversarial concurrency stress);
ongoing regression re-runs of the frozen summary eval / `REV-EVAL-01` comparison (`HRD-04`); real
storage-capacity and sustained-volume measurement (`HRD-05`/`PUB-02` — the arithmetic envelopes are
already in `ai-summary.md`); a permanent Compose `worker` service (`PUB-01`); full UI
integration/search/filter/sort polish and screenshots (`IMP-05`); similarity (`IMP-06`/`SIM-*`);
multi-day cross-generation corpus recurrence beyond "most recent terminal generation per known
platform route"; automatic generation-restart after a route goes `unstable`/`failed` (the job stays
visible and diagnosable, not silently retried forever or auto-restarted).

## Fixture provenance (built before the review-page parser existed)

Same non-negotiable rule as `IMP-02`/`IMP-03`: real sanitised fixtures before the parser,
independently-authored expected values. `research/feasibility/fixtures/metacritic/
reviews-pagination.json` (SPK-02) is itself a curated *summary*, not valid parser input — fresh raw
captures were mandatory.

| Capture | UTC | Bytes | SHA-256 |
|---|---|---:|---|
| Bayonetta (xbox-360) critic reviews, page 1 (offset=0) | 2026-09-12T03:25:21Z | 11,116 | `197afba3b55e60971ccf491bd71164dbdbc6208e984377b467871b333edebb33` |
| ...critic page 2 (offset=10) | 2026-09-12T03:26:24Z | 11,555 | `c14dc03208bcff8f9c3eb226275c7b4c5deb57cf650b218c4c861962ffa80de0` |
| ...critic last page (offset=80, 86 total) | 2026-09-12T03:26:25Z | 8,362 | `b1ace3cf0d4312bc7b522c9a84591ad6d8df35938b1ef94d3b70fcd7eadcee98` |
| ...user reviews, page 1 (offset=0) | 2026-09-12T03:26:01Z | 46,971 | `c2d8fd8c3d22f0d30170e8be2c0430ce7d06558d2567c3aa14423a8de0880b12` |
| ...user page 2 (offset=50) | 2026-09-12T03:26:36Z | 70,829 | `b0fe03e1583ea9ed4b95e28fd929930d77e9965622e91830990434a45b1f4711` |
| ...user last page (offset=100, 118 total) | 2026-09-12T03:26:37Z | 25,489 | `03957fa4d5ff49b1ed5686d720fa42f7847ec639d5f46c1fb99e72cc4a4409ff` |

Captured with `metacritic-ai-assignment-imp04/0.1`, same low-frequency single-request discipline as
`IMP-01/02/03`. `app/tests/fixtures/metacritic/review_page_{critic,user}_bayonetta_xbox360_*.json`
keep every field the parser reads verbatim (id/author/publicationSlug/publicationName/quote/score/
date/url, real `links.self`/`links.next` hrefs including genuine mojibake already present at the
source, e.g. `"Bayonetta�s"`) and drop only the `filterOptions`/`sortOptions`/`meta` blocks the
parser never reads. `review_pages_expected.json` is the independently-authored oracle: reported
total, item count, exact `next_cursor`, and first/last item's exact identity fields and full text
per fixture, read from the raw payload before `parse_review_page` existed.

**New real contract findings, confirmed live:**
- The real initial backend URL (discovered by fetching the web review page and reading its
  embedded `backend.metacritic.com/reviews/metacritic/{audience}/games/{slug}/platform/{slug}/web`
  link) uses `limit=10`/`sort=score` for critic and `limit=50`/`sort=date` for user, with
  `componentName={audience}-reviews`, `componentDisplayName={audience}+Reviews` (note: lower-case
  audience even in the display name — captured exactly, not corrected) — pinned once as a template
  in `metacritic/gateway.py`, never re-discovered per job; every subsequent page is reached only via
  the previous response's real `links.next.href`.
- Critic reviews on this route have no stable `id` field (`null` for all 86) and no `date` (`null`
  for all 86, even for recent-looking entries) — the fallback identity (publication slug + URL +
  label + score + normalized text) and a non-required date label are both real, not hypothetical,
  requirements.
- User reviews do carry a stable `id` (UUID) and a `date`.
- The terminal page's `links.next.href` is a real JSON `null` in both audiences (86/118 totals,
  confirmed exhausted), matching `SPK-02`'s `reviews-pagination.json` observation that `?page=N` is
  not a usable cursor for this contract.

## Exit-criterion audit

| Criterion | Independent evidence obtained | Remaining boundary |
|---|---|---|
| `AC-AI-01`/`AC-AI-02` (audience-separated grounded claims) | `test_summaries_contour.py` (schema/validation unit tests) + `test_summaries_worker.py::ColdSetTests` (real structural validation of a real Groq response) + **two real live summaries** (below), each with claims traceable to a real selected review | Full frozen rubric re-scoring is `SPK-05`'s own baseline (unchanged contour, reused verbatim) |
| `AC-AI-03` (no cross-audience leakage) | `contour.py`'s prompt/schema keep exactly one audience per request; `reviews/selection.py`/`corpus.py` never mix audience pools; live evidence: Orbitals' critic and user summaries were generated from disjoint corpora and show disjoint themes | `HRD-04` regression |
| `AC-AI-04` (insufficient-data guard) | `test_summaries_worker.py::InsufficientDataTests` — a corpus below 3 unique reviews never reaches the provider | Real live insufficient-data case not observed this cycle (both live corpora had ≥15 reviews) |
| `AC-AI-05` (cache hit / update-on-change) | `test_summaries_worker.py::UnchangedRepeatTests`/`ChangedInputStreamTests`; `ensure_job`'s `get_or_create` on `(game, audience, input_fingerprint, contour_fingerprint)` | — |
| `AC-AI-06` (failure isolation / diagnosable retry) | `test_summaries_worker.py::RateLimitedTests`/`MalformedOutputTests`/`LeaseLostMidAttemptTests`; **live**: a real `429`-equivalent quota deferral (below) recovered automatically with no data loss | `HRD-01` broader failure taxonomy |
| `AC-AI-07` (frozen eval threshold) | Reused verbatim: `contour.py`'s copied `prompt_3_0_0.md`/`output_schema_2_1_0.json` are SHA-256-pinned to `SPK-05`'s already-published frozen hashes (`test_summaries_contour.py::ContourFilesArePinnedTests`) — the exact contour that scored 96/98 | `HRD-04` regression re-run |
| Collection durability (review parser fixtures + expected extraction before parser; durable attempts/cursor; no data lost on retry/partial) | `test_reviews_collector.py` (14 tests: complete/empty/unstable×2/retryable/failed/idempotent-redelivery/lease-loss/real stale-lease recovery); `test_reviews_corpus.py` (real two-thread concurrent-build race); **live**: 30/30 real page fetches succeeded, 776 real reviews collected across 5 terminal routes with zero unstable/failed | `HRD-02`/`HRD-03` deeper concurrency stress |
| Candidate selection vs. `REV-EVAL-01` baseline, oracle unchanged | `evals/review_selection/verify_candidate.py`: **8/8 invariants pass** (the naive baseline scored 5/8) — see below | `HRD-04` regression |
| Cache/lease/quota reservation, explicit delayed-capacity, no paid fallback | `test_summaries_worker.py::QuotaExhaustionTests` (deferred without a provider call) + **live** quota exhaustion and recovery (below) | `HRD-05`/`PUB-02` real sustained-volume measurement |
| Backlog/oldest-age recorded; async queue not itself proof of capacity | `summaries/observability.py` + `test_summaries_observability.py` (3 tests); live snapshot after this cycle's real run: `arrivals=2, completed=2, outstanding=0` | Dedicated ops dashboard is `HRD-05`/`PUB-02` |

## `REV-EVAL-01` real-candidate result

```
$ PYTHONPATH=app python evals/review_selection/verify_candidate.py
all_pass=True failed=[]
PASS: the real candidate passes all 8 invariants on all applicable cases.
```

The real `reviews/selection.py` (hash-sort + cross-platform round-robin + dedup + token-boundary
truncation) passes every invariant `baseline_naive.py` failed
(`first_page_bias_trap.INV-PAGE-COVERAGE`, `last_page_bias_trap.INV-PAGE-COVERAGE`,
`cross_platform_duplicate_review.INV-DEDUP`) — the frozen oracle files were not touched;
`verify_candidate.py` only adapts between two independently-defined, field-identical dataclass
sets. This check now runs in `scripts/check.py`'s automated suite.

## Live runs against the real site and the real Groq API

`tiktoken` became a core project dependency this cycle (the production selection algorithm needs
real token counting, not just the eval harness); `pyproject.toml`/`uv.lock` updated accordingly.

**Review collection** (`scripts/run_worker.py --once`, repeated, plus one manual same-code drain of
a specific small game's jobs to avoid running up Elden Ring's much larger review counts just for
this proof): against the 182 real `ReviewCollectionJob` rows already sitting in the local dev
database from `IMP-02`/`IMP-03`'s own earlier live ingestion runs —

| Job | Game / platform | Audience | Pages | Reviews | Result |
|---|---|---|---:|---:|---|
| 1 | Elden Ring / Xbox One | critic | 1 | 0 | `empty` (valid real zero-total route) |
| 2 | Elden Ring / Xbox One | user | 3 | 121 | `complete` |
| 3 | Elden Ring / PC | critic | 7 | 63 | `complete` |
| 79 | Orbitals / Nintendo Switch 2 | critic | 8 | 77 | `complete` |
| 80 | Orbitals / Nintendo Switch 2 | user | 1 | 15 | `complete` |

30/30 real `review_page` fetches succeeded; 776 real `Review` rows and 776 `ReviewObservation` rows
persisted; zero `unstable`/`failed`/`retryable` outcomes. Elden Ring's remaining platforms (5
platforms × 2 audiences) were deliberately left `pending` rather than drained — a real, visible
backlog, not a hidden one, consistent with this cycle's "prove the mechanism, not full throughput"
scope boundary.

**Corpus + summary, end to end, real Groq calls**: Orbitals has one known platform per audience, so
completing both its jobs immediately triggered real corpus builds and `SummaryJob` creation
(`corpus.build`/`worker.ensure_job`, exercised live, not just in tests):

| Audience | Selected / fetched / reported | Result | Model | Tokens | Generated |
|---|---:|---|---|---:|---|
| critic | 10 / 77 / 77 | `succeeded` / `ok` | `openai/gpt-oss-20b` | 2,175 | 2026-09-12T04:03:49Z |
| user | 10 / 15 / 15 | `succeeded` / `ok` (after one real quota deferral — below) | `openai/gpt-oss-20b` | 1,942 | 2026-09-12T04:05:33Z |

Real critic summary (grounded, disjoint from the user summary's themes): likes included "stunning
retro-anime aesthetic," "charming co-op adventure," "inventive puzzles and exploration"; dislikes
included "camera often feels wrong," "story fails to land emotional beats," "imbalance between
players." Real user summary: likes included "co-op gameplay... challenging but enjoyable," "art
direction and animations... like an 80s anime"; dislikes included "lack of single-player mode,"
"story is weak and too short," "feels like a proof of concept." The public card at `/games/14/`
renders both, with model/generated-at/coverage counts and no raw review text, exactly as
`presentation/summaries.py` and the template implement.

**A real quota exhaustion and recovery, live, not simulated**: processing the user summary job
immediately after the critic one (both admitted at `GUARDED_RESERVATION_CEILING=6,800` tokens
against the real `8,000` TPM Free Plan limit) correctly deferred with `state=delayed_capacity`,
`last_error=quota_exhausted`, zero `SummaryAttempt` rows created (no provider call, no quota spent)
— exactly the "no paid fallback, explicit delayed state" contract. After the real clock passed the
computed `available_at`, reprocessing the same job succeeded normally. This is the same mechanism
`test_summaries_worker.py::QuotaExhaustionTests` exercises under a fake clock, now confirmed against
real wall-clock time and a real committed `SummaryAttempt` ledger.

## A real diagnostic-hygiene issue found live, not in a fixture

After the first real quota deferral, `SummaryJob.last_error` remained `"quota_exhausted"` even once
the job later reached `state="succeeded"` — an operator reading the row would see a
success state next to a stale failure reason. Neither `reviews/collector.py` nor
`summaries/worker.py`'s success paths cleared `last_error` on a later successful outcome. Fixed by
clearing `last_error` on every success/insufficient-data transition in both modules; confirmed via
the full test suite (142 Django tests, all green) and by re-observing the real Orbitals job rows.

## Two real bugs found by adversarial self-review before commit

A fork-based adversarial review of the full diff (before commit, following the same discipline
`IMP-02`/`IMP-03` used) found two real defects the test suite up to that point did not catch:

1. **No stale-lease recovery existed for either row-leased worker.** `reviews/collector.py` and
   `summaries/worker.py` both wrote `lease_expires_at` on claim but never read it anywhere;
   `claim_next_job` only ever considered `pending`/`retryable`(/`delayed_capacity`) rows, never
   `running`. A worker crashing or being killed between claiming a job and its next successful
   commit left that job **permanently stuck** in `running` — no restart, retry, or `--once`
   invocation would ever reclaim it. This is exactly the restart-persistence property `IMP-03`
   already built and tested for the analogous singleton-lease game-ingestion path
   (`processing.selector._recover_stale_candidates`); the per-row-lease equivalent was simply
   missing here. The existing "lease-loss" tests (`LeaseLostMidCollectionTests`/
   `LeaseLostMidAttemptTests`) only proved a stale worker can't *clobber* a job whose state was
   *already* reset by something else — nothing in production code ever performed that reset.
   Fixed by adding `_recover_stale_leases(now)` to both `claim_next_job` functions: any `running`
   row whose `lease_expires_at` has passed is swept back to `retryable` with its fencing token
   bumped immediately (not deferred to the next claim), so a late write from the presumed-dead
   worker is invalidated the moment staleness is recognised, mirroring `processing.selector`'s
   reasoning adapted to a per-row lease. New regression tests
   (`test_reviews_collector.py::ClaimNextJobTests::test_a_job_left_running_by_a_crash_is_reclaimed_once_its_lease_expires`/
   `test_a_late_page_from_a_recovered_job_does_not_commit`,
   `test_summaries_worker.py::StaleLeaseRecoveryTests`) prove real recovery, not just non-clobbering.
2. **`reviews/corpus.py::build()` had an unguarded check-then-create race.** It checked for an
   existing corpus with a plain `.filter(...).first()`, then called `.create()` with no lock and no
   `get_or_create` — under the `SELECT ... FOR UPDATE SKIP LOCKED` design, which explicitly expects
   concurrent workers, two workers completing the same game's last needed route at nearly the same
   time could both pass the check before either committed, crashing the second with an unhandled
   `IntegrityError` on `uq_review_corpus_game_audience_policy_fingerprint`.
   `summaries/worker.py::ensure_job` already avoided this correctly via `get_or_create`.
   Fixed by wrapping the create in `try`/`except IntegrityError`, re-fetching and returning the
   concurrent winner's row (safe: `build()` is a pure function of the same underlying reviews, so
   either worker's row is equivalent). A real two-thread `TransactionTestCase`
   (`test_reviews_corpus.py::ConcurrentBuildRaceTests`) exercises actual concurrent commits against
   the real database rather than simulating the interleaving, and passed: no crash, both threads
   agree on the same single persisted corpus.

Both fixes are covered by the 146-Django-test suite (up from 142 before this review pass), all
green, and did not require touching any already-verified behaviour.

## Tests

- `app/tests/test_metacritic_review_parser.py` (15): real Bayonetta fixtures, misroute rejection
  (audience/game/platform), structural-violation rejection, natural null identity/date preserved.
- `app/tests/test_reviews_selection.py` (8): cap/dedup/round-robin/determinism/truncation/
  no-fabrication unit tests for the pure algorithm, independent of `REV-EVAL-01`'s own harness.
- `app/tests/test_reviews_collector.py` (14): complete/empty/unstable (repeated page identity,
  changed total)/retryable+backoff/failed-after-5-attempts/idempotent redelivery/lease-loss
  mid-collection/corpus-and-summary-job trigger/**real stale-lease recovery after a simulated
  crash, plus proof a late write from the recovered-from worker cannot commit**.
- `app/tests/test_reviews_corpus.py` (1): a real two-thread `TransactionTestCase` racing
  `corpus.build()` against genuine concurrent commits — no crash, one agreed corpus.
- `app/tests/test_summaries_contour.py` (12): frozen-hash pinning, request payload shape, Groq
  strict-schema stripping, contour fingerprint determinism/sensitivity, output validation/
  normalization.
- `app/tests/test_summaries_worker.py` (9): cold set, unchanged repeat (cache hit), changed-input
  stream, quota exhaustion, `429` → delayed_capacity, malformed output → retryable, insufficient
  data (no provider call), lease-loss mid-attempt, **real stale-lease recovery** — the executable
  fake-provider workload `research/feasibility/ai-summary.md` requires before `G4`.
- `app/tests/test_summaries_observability.py` (3): arrivals/completed/outstanding counts, oldest
  outstanding age, no-outstanding-jobs edge case.
- `app/tests/test_presentation_summaries.py` (4): pending/ok/insufficient_data/stale card states.
- `evals/review_selection/test_score_selection.py` (unchanged, 9) +
  `verify_candidate.py` (new, real-candidate cross-check, now in `scripts/check.py`).

146 Django tests total (up from 80 after `IMP-03`; the 66 new tests are additive — every prior test
still passes unchanged).

## Verification commands

```powershell
uv lock                                         # tiktoken is now a core dependency
python scripts/check.py                         # ruff, mypy --strict, migrations, 142 Django tests,
                                                 # REV-EVAL-01 meta-tests + real-candidate cross-check
python scripts/provision_db.py                  # adds the worker role
python scripts/migrate.py
python scripts/run_worker.py --once             # one real tick (review page or summary attempt)
python scripts/run_worker.py                    # continuous mode
```

`scripts/check.py` passed locally against the local dev PostgreSQL 16 container. This is local
evidence, not a hosted CI run; the existing hosted CI workflow re-runs against this commit.

## Reproduction and pending input

No blocker. `IMP-05` (full UI integration checks, search/filter/sort, screenshots) is the next
dependent on the critical path — it can now show real summaries end to end. `HRD-01..05` own the
deeper failure-taxonomy, concurrency-stress, AI-regression, and storage/capacity evidence this
cycle's controlled simulations and one real live run point at, respectively. `PUB-01`/`PUB-02` own
turning the worker into a permanent, publicly-deployed, continuously-running service and measuring
real sustained throughput. `IMP-06`/`SIM-*` (similarity) remain independently available.
