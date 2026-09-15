# HRD-05: observability and security

Task `HRD-05`. Requirements/risks per `implementation_plan.md#hrd-05`:
run/game/job success, error, last success and backlog diagnosable; a
storage report measuring text versions, repeated observations, attempts,
indexes/WAL/backup and headroom on a representative corpus, not an
O(unique reviews) approximation; secret boundaries, escaping of untrusted
text, bounded logs and a safe reaction to storage shortage verified; the
operational instruction does not require a Bonus UI. Current task/gate
status belongs only to [action_plan.md](../../action_plan.md).

## Scope of this cycle

Unlike `HRD-01/03/04`, no diagnostics or storage-report capability existed
at all before this cycle -- `docs/design.md` names `observability` as a
component ("Structured events и представление persistent run/job state")
but only `summaries/observability.py` (the AI-queue backlog snapshot,
`IMP-04`) implemented it. Auditing security coverage found two concrete
gaps with zero existing tests; the rest (bounded logs, escaping's absence
of any bypass, atomic-rollback safety) already had structural or test
evidence to cite rather than duplicate.

## Fix

### Diagnostics

`processing/diagnostics.py` adds four read-only query functions, each
returning a JSON-serializable dict, alongside the existing
`summaries.observability.backlog_snapshot`:

- `run_diagnostics(run_id)` -- one `ProcessingRun`'s status, error code, and
  selected/processed/failed counts.
- `game_diagnostics(game_id)` -- the latest `DailyCandidate` outcome (and
  its own last `processed` business date), plus every `ReviewCollectionJob`
  and `SummaryJob` for that game with their own state/error.
- `job_diagnostics(kind, job_id)` -- one review-collection or summary job's
  state/error/attempt history.
- `backlog_diagnostics(clock)` -- the full state breakdown for both
  `DailyCandidate` and `ReviewCollectionJob` (every state, not a filtered
  "in-flight" subset -- see Adversarial review), plus the existing AI
  queue snapshot -- backlog across the whole pipeline, not only the AI
  queue.

`processing/management/commands/diagnose.py` and `scripts/diagnose.py`
expose these as `python scripts/diagnose.py --run|--game|--job|--backlog
<id>`, printing one JSON object. The script runs under `WEB_DB_USER` --
the same SELECT-only role the public preview already uses -- so
diagnostics can only read, matching `docs/design.md`'s "not a separate
storage/monitoring service" framing: no new tables, no new write path.

### Storage report

`processing/storage_report.py` measures, via plain SQL against whatever
database Django is configured against:

- `pg_database_size`/`pg_total_relation_size` for the storage-relevant
  tables (`review`, `review_observation`, `catalog_sourcefetch`,
  `summary_attempt`, `review_corpus_item`, `game`), read from each model's
  own `_meta.db_table` rather than hardcoded strings.
- WAL size via `pg_ls_waldir()`, which needs superuser/`pg_monitor` --
  under the deliberately least-privileged web role this returns `None`
  rather than crashing the whole report.
- Disk headroom (`total`/`used`/`free`) for a given path via
  `shutil.disk_usage`.
- Three overhead ratios the exit criterion explicitly warns an
  O(unique reviews) estimate would miss: saved text versions per identity
  (`Review` rows sharing an `identity_key` but a different
  `version_sha256`, e.g. an edited review re-observed), observations per
  review (`ReviewObservation` rows per `Review` row -- the same review
  text observed again across more than one collection generation), and
  provider attempts per terminal `SummaryJob` (retries that still consumed
  quota even though the job's final state reused nothing from them).

`processing/management/commands/storage_report.py` and
`scripts/storage_report.py` expose this as `python scripts/storage_report.py
[--disk-path <path>]`, also under `WEB_DB_USER`.

**Explicit scope boundary, not a gap:** this cycle builds and verifies the
*measurement tool* deterministically, against a seeded dataset with a
known non-trivial multiplier (below). Running it against a real
production-representative corpus to produce an actual storage forecast and
real disk headroom is `PUB-02`'s own stated scope ("Измерены storage
forecast ... на реальных данных"), not duplicated here -- the same
live-vs-CI boundary this project already draws for `HRD-01`'s "Отдельный
controlled live check не включается в deterministic CI" and equivalent
lines elsewhere. No representative-scale local database exists in this
environment to run it against honestly (the local application database is
unmigrated, per `action_plan.md`), which reinforced rather than caused
that boundary.

### Security

- **Fixed (zero prior coverage):** `groq_adapter._safe_api_error` already
  redacted the operator's API key from a provider error body, but nothing
  proved it end-to-end through `generate_summary` for the case that
  actually matters -- a `GroqApiError` message that is stored verbatim
  into `SummaryAttempt`/`candidate.last_error` and can reach bounded logs.
  `test_groq_adapter.py::ApiKeyRedactionTests` simulates a 401 response
  whose body echoes the API key back (the worst realistic case) and
  asserts the raised error's message contains `[REDACTED]`, never the raw
  key.
- **Fixed (zero prior coverage):** no test proved untrusted source text
  survives template rendering escaped. `grep -rn '|safe\|mark_safe'
  app/presentation` finds zero uses anywhere in the app, so Django's
  default auto-escaping is the only, and structurally confirmed-unbypassed,
  defense for every rendered field (title, developer, description, claim
  text, genres, platform names alike) -- one concrete adversarial payload
  through the template (`test_presentation_game_detail.py::test_untrusted_source_text_is_escaped_not_rendered_as_html`)
  exercises that same general mechanism a per-field test would only repeat.
- **Already covered, cited not duplicated:** bounded logs
  (`config/safe_logging.py`'s `SafeFormatter`, tested in `test_health.py`
  -- never logs free-form exception/request text, only the exception type
  name); safe reaction to a failed write for any reason, storage
  exhaustion included (every mutation runs inside `transaction.atomic()`;
  `test_catalog_constraints.py`'s `IntegrityError` tests and
  `test_catalog_ingest.py::test_a_failure_creating_jobs_rolls_back_the_whole_transaction`
  already exercise the same atomic-rollback guarantee Postgres provides
  regardless of *why* a write failed -- a constraint violation and an
  out-of-space `OperationalError` hit the identical rollback path).

### Operational guide

Added an "Operations" section to `README.md` documenting both scripts'
usage and the security boundaries above, satisfying "инструкция не
требует Bonus UI" with plain CLI/JSON, no new UI component.

## Adversarial review

An independent `/code-review high` pass found three items, all fixed:

- **Fixed:** `backlog_diagnostics`'s review-job rollup filtered to
  `("pending", "running", "retryable")`, silently excluding `unstable` (and
  `failed`) jobs from the aggregate count -- exactly the jobs
  `reviews/collector.py` documents as staying "visible and diagnosable"
  rather than being auto-restarted, so this is precisely the surface that
  must not drop them. Changed to a full, unfiltered state histogram for
  `ReviewCollectionJob`, matching `DailyCandidate`'s own rollup (which
  already reported every state) -- this also resolved a second finding,
  that the two rollups under one "outstanding work" function were
  inconsistently scoped (one filtered, one not). A new regression case
  (a third game with an `unstable` job) confirms it now appears.
- **Fixed:** `_table_size_bytes`/`_wal_size_bytes` caught any DB error with
  a bare `except Exception` but never protected the query with its own
  savepoint. `pg_ls_waldir()`'s expected permission-denied failure under
  the least-privileged web role would abort PostgreSQL's whole surrounding
  transaction, not just that one query -- true for every Django `TestCase`
  test, and for any future caller run inside `transaction.atomic()` -- so
  the *next* query anywhere in that transaction would fail with a
  misleading "current transaction is aborted" instead of the real, already
  swallowed cause. Fixed by wrapping each risky query in its own
  `transaction.atomic()` (a nested `atomic()` opens a SAVEPOINT when
  already inside a transaction). A new test exercises the real
  permission-denied path (the test DB role genuinely lacks
  superuser/`pg_monitor`, so `wal_size_bytes` is asserted `None`, not
  simulated) and confirms a normal query still succeeds immediately after.

## Verification that the tests carry real signal

- `ApiKeyRedactionTests`: temporarily removed the `.replace(api_key,
  "[REDACTED]")` call in `_safe_api_error` -- the test failed with the raw
  secret found in the error message. Restored with no diff against the
  original file.
- `StorageReportOverheadTests`: temporarily changed `review_count` to
  count distinct identities (collapsing exactly to the O(unique reviews)
  approximation the exit criterion warns against) and `terminal_job_count`
  to count all jobs regardless of state -- the text-version-ratio
  assertions failed (`1 != 2`). Restored with no diff against the original
  file.

## Verification

339 application tests (15 added: 4 diagnostics function tests + 3 command
tests + 4 storage-report tests (including the adversarial-review
transaction-poisoning regression) + 1 API-key redaction test + 1 escaping
test + 2 empty/edge cases) and the full `scripts/check.py` suite (ruff
format/lint, strict mypy, migration drift, static build, all offline
evals/verifiers) pass green locally. This closes `HRD-05`: run/game/job/
backlog are diagnosable by ID via a plain CLI; the storage report tool is
built and verified against real overhead, with its representative-corpus
run correctly deferred to `PUB-02`; secret boundaries and escaping have
new regression coverage; bounded logs and safe-failure behavior are cited
from existing coverage. `HRD-05` moves to `Verified`.
