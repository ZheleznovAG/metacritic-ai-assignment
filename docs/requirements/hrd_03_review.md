# HRD-03: real concurrent claimant safety

Task `HRD-03`. Requirements/risks per `implementation_plan.md#hrd-03`: two
claimants starting synchronously on PostgreSQL; only the current owner
confirms core/page/summary success; stale owner, reclaim, late response,
redelivery and the absence of double counters/claims all verified; tests
must not substitute SQLite for the accepted backend. Current task/gate
status belongs only to [action_plan.md](../../action_plan.md).

## Scope of this cycle

Auditing the existing suite against each clause of `HRD-03`'s exit
criterion found five of the six already covered by prior cycles, each on
real PostgreSQL 16 (never SQLite):

| Clause | Existing coverage |
|---|---|
| Stale owner / reclaim | `AbandonedRunRecoveryTests` (scheduler run), `ClaimNextJobTests.test_a_job_left_running_by_a_crash_is_reclaimed_once_its_lease_expires` (review job), `StaleLeaseRecoveryTests` (summary job) |
| Late response (only the current owner commits) | `LeaseStealingGateway`-driven `test_a_lease_lost_mid_batch_backfills_accurate_counters_from_committed_attempts` (core), `ClaimNextJobTests.test_a_late_page_from_a_recovered_job_does_not_commit` (review page), the equivalent stale-attempt test in `test_summaries_worker.py` (summary) |
| Redelivery | `test_collection_attempts.py` (`IMP-04` R08/R11: terminal/in-flight redelivery) |

The one gap: every one of the above runs on Django's `TestCase`, which
wraps the whole test in a single transaction on a single connection — real
concurrent claimants can never occur there, so none of it actually exercises
PostgreSQL's row-level locking under genuine concurrency. It proves the
*recovery logic* is correct for a known interleaving, not that
`select_for_update()`/`select_for_update(skip_locked=True)` actually
serializes two claimants that start at the same instant, which is exactly
what "два претендента... синхронно стартуют на PostgreSQL" asks for. This
cycle closes that one gap for the three real concurrent-claimant surfaces
in the system:

- `processing.lease.acquire_lease` — the singleton `ProcessingLease` that
  gates who runs a given hour's scheduler tick.
- `reviews.collector.claim_next_job` — one row-leased `ReviewCollectionJob`
  claimed by one of potentially several review-collector worker processes.
- `summaries.worker.claim_next_job` — the equivalent claim for
  `SummaryJob`.

(`processing.selector`'s `DailyCandidate` claiming was not added to this
list: it is only ever driven from inside the single lease-holding scheduler
process, so it has no analogous multi-claimant surface to test.)

## Fix

No production code changed. Three new `TransactionTestCase`s (real,
separate PostgreSQL connections per thread, `connections.close_all()` in
each thread's `finally`) were added, following the same pattern already
established by `test_reviews_corpus.py::ConcurrentBuildRaceTests`:

- `test_processing_scheduler.py::LeaseAcquisitionRaceTests` — two real
  threads, synchronized with a `threading.Barrier`, race
  `processing.lease.acquire_lease` for the same pre-existing lease
  resource. Asserts exactly one wins (gets a fencing token), the other
  raises `LeaseOverlap`, and the lease row ends up owned by the winner with
  a matching token.
- `test_reviews_collector.py::ClaimNextJobRaceTests` — two real threads
  race `claim_next_job` for one pending `ReviewCollectionJob`; asserts
  exactly one claims it (fencing token bumped once, one `running` row).
  A second test gives each thread its own job and asserts both succeed
  with no lost or duplicated claim.
- `test_summaries_worker.py::ClaimNextJobRaceTests` — the same two cases
  for `summaries.worker.claim_next_job`/`SummaryJob`.

## Adversarial review

An independent `/code-review high` pass (8 finder angles across three fork
agents plus a direct conventions check; empirically re-ran the affected
tests and `mypy --strict`) found one candidate that survived to
verification, and refuted one it also checked:

- **Refuted:** a hypothetical future deadlock could leave a thread blocked
  past the test's `join(timeout=10)`, holding a row lock. Traced to
  `app/config/settings.py`'s `statement_timeout=5000` on the test DB
  connection: PostgreSQL itself kills any blocked `select_for_update()`
  after 5s, well under the 10s join timeout, and the resulting exception is
  already caught and recorded. Not a real gap.
- **Fixed:** the barrier/thread/connection-cleanup harness was duplicated
  five times across the three new test classes (six counting the
  pre-existing `ConcurrentBuildRaceTests` pattern in `test_reviews_corpus.py`
  this cycle copied from). Extracted into a shared
  `tests/concurrency.run_concurrently()` helper and all five new call sites
  updated to use it; `test_reviews_corpus.py`'s own pre-existing copy was
  left as-is, since refactoring code this diff didn't touch is out of this
  cycle's scope.

Extracting the helper surfaced a real `mypy --strict` inference quirk
(confirmed with a minimal repro, `mypy` 1.20.2): a PEP 695 generic function
declared as `def f[T](*targets: Callable[[], T]) -> tuple[list[T | None], ...]`
infers `T` as the bare type (e.g. `Job`) from the return position's `T | None`
decomposition, then rejects every caller whose target actually returns
`Job | None` — the exact shape every real call site here has. Fixed by
changing the parameter itself to `Callable[[], T | None]`, which resolves
correctly; no lambda involved (each call site was already using a named
inner function with an explicit return annotation, needed to avoid a
similar lambda-inference issue upstream of this one).

## Verification that the tests carry real signal

Before committing, `reviews/collector.py`'s `select_for_update(skip_locked=True)`
was temporarily removed and the new
`test_two_real_threads_racing_for_one_job_never_both_claim_it` test was run
five times in a row: it failed 3 of 5 runs (a genuine double-claim,
timing-dependent as real thread races are) with the lock removed, then
passed cleanly every time once the lock was restored — confirming the test
detects the real regression rather than passing vacuously. The fix was
then restored with no diff against the original file (`git diff` empty).

## Verification

317 application tests (5 added) and the full `scripts/check.py` suite
(ruff format/lint, strict mypy, migration drift, static build, all offline
evals/verifiers) pass green locally. This closes `HRD-03`: combined with
the pre-existing stale-owner/reclaim/late-response/redelivery coverage
above (already real-PostgreSQL, never SQLite), all clauses of the exit
criterion now have evidence; `HRD-03` moves to `Verified`.
