# FIN-ARCH: worker composition and dependency review

## Scope and exit criteria

Post-submission cleanup for RUN-01, AI-01–03, SIM-01, YTP-03, NFR-01–06 and
R-OPS-01 / R-TST-01. Status belongs to [action_plan.md](../../action_plan.md).

- Move cross-domain worker dispatch/entry point out of `reviews` into a small
  `orchestration` package; keep the public `run_worker [--once]` command unchanged.
- Preserve durable review/summary alternation, queue priority, idle-only similarity
  and Let's Play work, provider failure isolation and resource/heartbeat lifecycle.
- Keep PostgreSQL state/leases/migrations unchanged. Do not move `EnrichmentTurn`
  ownership or weaken atomic review/corpus/summary intent for a cleaner import graph.
- Derive the before/after package graph and complexity hotspots from source; forbid
  domain imports of the composition root and ensure new packages cannot evade scanning.
- Split only a confirmed hotspot at an existing boundary, preserving game lock,
  fencing checks, fetch evidence and terminal corpus/summary transaction semantics.
- Adversarial review, fixture regressions, canonical build/container suite and smoke;
  one focused commit. No provider/ranking changes, hosted deployment or new feature.

## Findings and verification

### Findings, changes and counterexamples

The pre-edit [inventory](../evidence/fin-arch/before.json) found 21 non-foundation
package edges and five simple directed cycles. `reviews` owned the main worker
command even though it imported Let's Play, similarity upkeep, monitoring and
summary services. That import completed `reviews → letsplays → summaries → reviews`.

The command now lives in `orchestration/management/commands/run_worker.py`, with
durable dispatch in `orchestration/jobs.py`. Django registers the new package and
discovers the same `run_worker` name; no compatibility command remains in `reviews`
because such a backwards import would create another composition-root cycle.
`scripts/run_worker.py` and the Compose command need no change. `EnrichmentTurn`
stays in `reviews`, with its table, locks and durable next-kind unchanged.

The [after inventory](../evidence/fin-arch/after.json) has four cycles, no imports
into `orchestration`, and no `reviews → letsplays` edge. Total edges rise from 21
to 26 because the new root explicitly names six existing dependencies; this is
not a claim that every coupling disappeared. The fitness test now checks all
regular production packages and rejects any import back into the composition root.
The existing exact allowlist, pure-package/core rules and web/no-numpy test remain.

`collect_one_page` was 198 lines / 22 branch AST nodes. It now has 47 lines / 3
nodes for intent and fetch; `_commit_page` has 173 lines / 19 nodes for committing
the response and terminal handoff. The combined decisions are preserved, not
deleted. The actual transactional block is identical by AST, including game lock
before ownership checks, superseded fetch handling, retry limits, generation
restarts, review versions/observations and atomic corpus/summary intent.

The independent [source-preservation countercheck](../evidence/fin-arch/preservation.json)
compares that whole transaction, its return, the dispatcher function and the worker
command class against `9b82da0`; only the command's dispatch alias is normalized.
Formatting/locations are ignored. This supports the mechanical move; it does not
replace executable PostgreSQL boundary tests.

Adversarial checks include:

- Moving the command could silently remove it from Django discovery. The new test
  resolves `get_commands()['run_worker']` to `orchestration`; the updated supervised
  runtime and live worker heartbeat provide a separate deployment observation.
- A pure-looking package must not pull ranking into web startup. Its `__init__`
  is inert; the fresh-interpreter no-numpy route test still passes.
- Idle work must never delay a busy review/summary queue. Existing real dispatch
  fairness tests cover durable alternation, unavailable jobs, disabled credentials
  and restarts; new tests cover busy review exclusion and similarity-before-Let's Play
  ordering. No database dispatch lock survives into either kind of HTTP.
- Provider failure must not kill the worker or expose its details. A raised fixture
  Let's Play failure is isolated and only the exception type is logged. `--once`
  closes both clients on success and tick failure.
- The collector split must not commit a terminal page without its summary intent.
  Existing rollback/reclaim, crash-after-commit, concurrent intent visibility,
  redelivery and lost-lease tests run in the full suite.
- The first focused run caught an omitted explicit `orchestration → metacritic`
  protocol edge. It was reviewed and added; final focused/suite outcomes below
  supersede that failed candidate. A new test's initial mypy buffer-type error
  was corrected by retaining its explicit `StringIO`, not weakening type checks.

### Independent verification

[Focused checks](../evidence/fin-arch/focused.txt): 14 architecture/orchestration
tests, no database setup. [Canonical checks and smoke](../evidence/fin-arch/checks.txt):
build/suite exit 0, Ruff, strict mypy (191 files), Django checks, no migration drift,
586 application tests, 22 script tests and all offline evaluations. The normal
suite includes the processing-to-browser journey, role boundaries, recovery and
existing review/summary/provider-budget tests. Smoke passes all eight checks.

[Source/image verification](../evidence/fin-arch/verification.json) records the
parent SHA, app/audit source hashes and built/checks/running-web/running-worker
image identities. A [live runtime observation](../evidence/fin-arch/runtime.json)
records a fresh, non-overdue worker heartbeat after the update.
An independent no-network probe compares actual app source
bytes in both images to the host hashes, excluding generated `staticfiles`.
The local app was updated only after the suite passed; worker command, shared
image and fresh heartbeat are observed without invoking paid providers for tests.

Reproduce the source audit with the [dated commands](../../research/reviews/20261005_fin_arch/README.md).
The commands use only standard-library AST/Git reads and are separate from CI;
the runtime/fitness regressions are in the existing canonical CI suite.

### Retained boundaries and limits

Four static import cycles remain: `catalog ↔ similarity` (frozen legacy baseline),
`processing ↔ reviews`, `reviews ↔ summaries`, and
`processing → summaries → reviews → processing`. Corpus token diagnostics and
atomic summary handoff still depend on summaries; collection readiness still
reads processing cohorts. Replacing these with indirect model lookup or moving
state into a new package would hide coupling or expand the schema/transaction
scope. This cleanup makes no claim of a fully acyclic domain model.

The measured unchanged hotspots are `summaries.worker.process_job` (176 lines / 25
branch nodes), `processing.selector.run_batch` (129 / 22), and `reviews.corpus.build`
(179 / 10). Let's Play `advance` is already a 10-line dispatcher; its larger `_hear`
(84 / 19) implements provider-unit reservations and fallback bookkeeping. Their
existing boundary tests pass; no additional runtime defect justified splitting
those contracts in this cycle. Counts are descriptive AST measurements, not a
quality score or proof of global complexity reduction.

The durable identity-quarantine proposal remains separate optional schema work;
the existing explicit source exclusion is preserved. The archived `6551e42` probe
uses its former worker imports and must run from that reviewed revision; active
README/Bonus 2 worker references are updated, historical findings are not rewritten.
No hosted CI/public deployment, provider-quality improvement, ranking-policy change
or new data migration is asserted by this local evidence.
