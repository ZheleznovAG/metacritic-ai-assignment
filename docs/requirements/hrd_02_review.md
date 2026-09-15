# HRD-02: scheduler run recovery

Task `HRD-02`. Requirements/risks per `implementation_plan.md#hrd-02`:
idempotency and recovery — no lost intent, duplicates, lost cursor, or
overwritten terminal history across a real PostgreSQL crash/restart. Current
task/gate status belongs only to [action_plan.md](../../action_plan.md).

## Trigger

An independent audit (`docs/requirements/implementation_audit_f0e89a4.md`,
finding `A05`) reviewed the code and found that `processing/scheduler.py`'s
`run_tick` looked up an existing `ProcessingRun` by `trigger_key` and, if
found, unconditionally returned `skipped_duplicate` — regardless of that
run's actual `status`. A process that crashed between creating the run row
(`status="queued"`) and acquiring the singleton ingestion lease, or crashed
mid-batch after acquiring it (`status="running"`), left a permanently
stranded row: every later tick for that same UTC hour saw the row already
existed and skipped it without ever finishing the work, and the row itself
stayed `queued`/`running` forever with `ended_at=null`. The audit's own
counterexample (an isolated PostgreSQL check) reproduced exactly this: a
crash before `acquire_lease` left `queued`; a retry one minute later called
no gateway and returned `skipped_duplicate`; the next hour's independent
work succeeded normally, but the original stranded row was never reaped.
The audit explicitly did not claim total daily-progress loss — the stranded
row is a bookkeeping/availability defect, not a data-loss one — but it is a
real gap in exactly what `HRD-02` exists to close.

## Fix

`run_tick` now distinguishes terminal `ProcessingRun` statuses
(`succeeded`/`partial`/`failed`/`skipped_duplicate`/`skipped_overlap`) from
non-terminal ones (`queued`/`running`, `RESUMABLE_STATUSES`). On a
non-terminal match for the current hour's `trigger_key`, a new `_try_resume`
helper takes over the *same* row — under `select_for_update()` and a
re-check of its status inside that lock, then the existing `acquire_lease`
call — instead of only ever reporting `skipped_duplicate`. This reuses all
of the pre-existing lease/fencing-token safety machinery unchanged:
`acquire_lease` still raises `LeaseOverlap` if the row is genuinely owned by
a live process (its lease unexpired), so a resume attempt against a run
that is actually still in progress correctly backs off without touching
that row; `run_batch`'s own `_recover_stale_candidates` step (already
built for `IMP-03`'s per-candidate crash recovery, `PS-08`) already
tolerates being invoked on a resumed run with no changes needed, since it
always reclaims leftover `state="processing"` rows under the previous
fencing token and always recomputes `run.selected_count`/counts fresh from
what it actually processes in that call — nothing in it assumed a run was
freshly created. `_execute_and_close` (the former second half of `run_tick`)
is shared unchanged between the fresh-create and resume paths.

`_mark_running` preserves an already-set `business_day`/`started_at`
(`run.business_day or now.date()`) rather than resetting them on resume, so
a resumed run keeps its original semantic start time.

## Adversarial review

`/code-review high` on the diff found two issues, both addressed or
explicitly scoped:

- **Fixed (real bug):** a concurrent resumer could finish the run *for real*
  (a genuine `succeeded` outcome with real counts) in the window between
  `run_tick`'s initial unlocked read of `existing` and `_try_resume`'s own
  row lock. If `_try_resume` then correctly found nothing left to resume and
  returned `None`, the caller was still returning the stale in-memory
  `existing`/`winner` snapshot (e.g. `status="running"`, zero counts) instead
  of the row's real, just-committed terminal state — misleading any caller
  reading `TickResult.run` (e.g. `run_scheduler.py`'s per-tick log line).
  Fixed by calling `existing.refresh_from_db()`/`winner.refresh_from_db()`
  before falling back to `skipped_duplicate` in that branch. A dedicated
  regression test (`test_a_run_that_finished_between_the_lookup_and_the_resume_attempt_reports_its_real_outcome`)
  simulates the race via a patched `_try_resume` that commits a terminal
  outcome as its side effect before returning `None`; confirmed to fail
  without the fix (`'queued' != 'succeeded'`) and pass with it.
- **Accepted as an explicit scope boundary, not a regression:** resume is
  reached only via an exact `trigger_key` match, so a crash near the very
  end of an hour that is not retried again before the hour rolls over
  leaves that specific hour's row permanently stuck (a cross-slot orphan,
  distinct from the same-slot case `A05` and this fix target). This is
  precisely the boundary the audit itself drew ("recovery skip *in the
  current slot*", not a claim about every possible crash timing) and is not
  newly introduced by this change — the pre-fix code had no reaping path at
  all, in-slot or cross-slot. A general status-based reaper (independent of
  `trigger_key`) is a reasonable future hardening item but is out of this
  cycle's narrow, audit-driven scope.

## Incidental fix: `A06` (Groq client timeout ignored)

While in `app/summaries/` for an unrelated reason during the same audit
review, `A06` was also closed: `groq_adapter._post` passed an explicit
`timeout=DEFAULT_TIMEOUT_SECONDS` (180.0) to every `client.post()` call,
which httpx applies as a full per-request override — silently ignoring
whatever timeout the caller's `httpx.Client` was actually constructed with
(`run_worker.py` correctly builds it from the operator's
`GROQ_API_TIMEOUT_SECONDS`). Removed the override so the client's own
configured timeout reaches the request; removed the now-dead
`DEFAULT_TIMEOUT_SECONDS` constant. A new dedicated test
(`test_groq_adapter.py::RequestTimeoutTests`) constructs a client with a
distinctive `httpx.Timeout(37.5)` and asserts, via `MockTransport`
inspecting `request.extensions["timeout"]`, that exact value reaches the
request. An existing test in `test_summary_admission.py` had hardcoded an
assertion of `timeout == 180` on every request — unintentionally locking in
the bug as "expected" behavior; that incidental assertion (unrelated to the
test's actual subject, payload measurement/reservation) was removed rather
than updated to a different magic number, since the dedicated adapter-level
test now owns that behavior. This finding was filed under `HRD-04` by the
audit, not `HRD-02`; it is recorded here because it was fixed in this cycle,
and `HRD-04`'s own review will reference this entry rather than reopening it.

## Verification

298 application tests (4 added: 3 in `AbandonedRunRecoveryTests` covering
crash-before-lease, crash-mid-batch-with-natural-TTL-expiry, and
still-live-run-must-not-be-touched; 1 in `test_groq_adapter.py`), full
`scripts/check.py` (ruff format/lint, strict mypy on 111 source files,
Django checks, migration drift, static build, all offline
evals/verifiers) — all green locally. All four pre-existing
`RunTickTests`/`RunTickTests`-adjacent tests pass unchanged, confirming the
fix is additive and does not alter any previously-verified behavior
(a genuinely terminal run for the current hour is still reported as
`skipped_duplicate` with no gateway call, per
`test_a_repeat_tick_in_the_same_hour_does_not_fetch_again`).

Not yet done as part of this cycle: the broader `HRD-02` matrix items that
were already covered by `IMP-03`'s existing tests (`PS-03` retry-first,
`PS-08` per-candidate crash recovery, `PS-09` next-page-failure cursor
safety) were re-verified as still passing but not re-derived from scratch,
since `A05` was the concrete, previously-unproven gap this cycle targeted.
Cross-slot orphan reaping (the accepted scope boundary above) and the
audit's other independent findings (`A01`–`A04`, `A07`–`A10`) remain open
for their own cycles (`HRD-01`/`03`/`04`/`05`, `PUB-01`/`02`, delivery
documentation).
