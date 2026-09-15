# HRD-06: combined offline suite and G5 gate audit

Task `HRD-06`. Requirements/risks per `implementation_plan.md#hrd-06`: on
one verifiable state, static/build, unit/fixture/integration/failure/
concurrency, AI/similarity and E2E all pass; every critical risk has
evidence or an explicitly accepted limitation; runtime/API live checks
stay separate; `G5` gets links to the actual reports. Current task/gate
status belongs only to [action_plan.md](../../action_plan.md).

## Scope of this cycle

Unlike `HRD-01`–`HRD-05`, this cycle adds no new code. It runs the whole
offline suite together, once, on one committed state, and audits every
`docs/risks.md` risk that names an `HRD-*` task as its owner or next
verification step against the evidence those five cycles actually
produced -- confirming the audit trail is real, not asserting it from the
individual review docs' own claims alone.

## Combined suite, one state

`scripts/check.py` was run fresh against commit `ea710ce` (clean working
tree, no uncommitted changes) as a single invocation -- not stitched
together from separate runs at different times:

| Stage | Result |
|---|---|
| `ruff format --check`, `ruff check` | PASS |
| `mypy` (strict, full source tree) | PASS |
| `manage.py check`, `makemigrations --check --dry-run` | PASS |
| `collectstatic` | PASS |
| `manage.py test tests` (unit/fixture/integration/failure/concurrency/E2E) | **339 tests**, PASS -- includes `test_e2e.py`'s mandatory Chromium journey, `HRD-03`'s real-thread concurrency races, `HRD-01/02/04`'s failure-injection tests, and every `IMP-*` fixture/integration test |
| `scripts/tests` (deployment/permission counterexamples) | 6 tests, PASS |
| `research/planning` (baseline plan graph/budget checks) | 18 tests, PASS |
| `evals/reviews` (`REV-EVAL-01`/`SPK-05` frozen selection+quality suite) | 7 tests + `score_run.py --verify`, PASS |
| `evals/review_selection` (production-candidate vs. frozen oracle) | 9 tests + `verify_candidate.py`: 8/8 invariants, PASS |
| `evals/similarity` (`SIM-EVAL-01` frozen oracle + comparison) | 14 tests + `compare.py`: genre Jaccard 1.0.0 selected, all invariants, PASS |

Total: 393 tests plus the offline eval/verifier scripts, all green in one
pass. No live Metacritic or paid-provider call occurs anywhere in this
suite (per `AGENTS.md`'s "deterministic CI must use fixtures/fakes"
rule, unchanged this cycle) -- runtime/API live checks (the `IMP-02/03/04/07`
live verification cycles, the `f0e89a4` audit's VDS snapshot) are already
separate from, and were not re-run as part of, this deterministic pass.

## Risk coverage audit

Auditing `docs/risks.md` for every risk naming an `HRD-*` task as owner or
next verification step (risks.md's own dispositions are a pre-implementation
snapshot per its stated update rule -- "correction-статусы принадлежат
action_plan.md" -- so this table gives each one's *current* status against
the evidence produced, not a rewrite of risks.md itself):

| Risk | `HRD-*` verification named | Evidence now |
|---|---|---|
| `R-EXT-01` | `HRD-01` (HTTP-adapter half) | [hrd_01_review.md](hrd_01_review.md): bounded size/time, transient-failure retry. `PUB-01`'s live-frequency/full-contract portion remains explicitly separate, unaffected. |
| `R-EXT-03` | `HRD-01` (extended failure cases) | [hrd_01_review.md](hrd_01_review.md): both halves (HTTP-adapter bounds and the `IMP-02` degraded-extraction known limitation) closed. |
| `R-EXT-04` | `HRD-01` | Same evidence as `R-EXT-03`. |
| `R-AI-01` | `IMP-04/HRD-04` | [hrd_04_review.md](hrd_04_review.md): timeout isolation, prompt-injection structural containment; malformed-output/grounding coverage already existed and is confirmed still green. |
| `R-AI-02` | `IMP-04/HRD-04` (capacity regression); `PUB-02` (production capacity) | [hrd_04_review.md](hrd_04_review.md) confirms capacity/cache/version checks repeated and pass; `PUB-02`'s real-environment arrivals/backlog measurement remains explicitly future, unaffected by this cycle. |
| `R-ID-01` | `HRD-02–HRD-03` | [hrd_02_review.md](hrd_02_review.md) (stranded-run resume), [hrd_03_review.md](hrd_03_review.md) (real concurrent-claim proof for the singleton lease and both row-leased job queues) -- the "executable unique/concurrency tests" this risk's disposition called for now exist. |
| `R-TIM-01` | `IMP-03/HRD-02` | [hrd_02_review.md](hrd_02_review.md): scheduler resume closes the automated-evidence gap this risk's disposition named. |
| `R-TIM-02` | `IMP-03/HRD-02–HRD-03` | Same two review docs as `R-ID-01`: the "failure/concurrency evidence" this risk's disposition called for is now real-thread, real-PostgreSQL evidence, not simulated interleaving alone. |
| `R-DAT-01` | `IMP-02–IMP-04/HRD-01–HRD-02` | [hrd_01_review.md](hrd_01_review.md) + [hrd_02_review.md](hrd_02_review.md): destructive-update/partial-processing failure tests this risk's disposition called for exist (`_recover_stale_leases`, stranded-run resume, degraded-extraction diagnosis). |
| `R-OPS-01` | `HRD-05/PUB-02` | [hrd_05_review.md](hrd_05_review.md): the operational diagnostic contract (run/game/job/backlog by ID) this risk's disposition called for now exists via `scripts/diagnose.py`. `PUB-02`'s two-application-window production evidence remains explicitly future. |
| `R-TST-01` | `HRD-06` (this task) | This document's own combined-suite run above: the curated Metacritic fixtures (`SPK-02`) and frozen AI cases (`SPK-05`) this risk's disposition named now run together, in one pass, as the executable fake-provider/fixture suite this risk called for. Live contract checks remain a separate, controlled activity, per the same disposition. |
| `R-SEC-01` | `HRD-05` (config review, security tests); `REL-03` (archive scan) | [hrd_05_review.md](hrd_05_review.md): API-key redaction and template-escaping now have regression tests; bounded logs and atomic-rollback safety cited from existing evidence. `REL-03`'s archive privacy scan remains a separate future delivery task. |

Risks not in this table either name no `HRD-*` task (`R-DEP-01/02`,
`R-DEL-01`, `R-PLN-01`, `R-REP-01`, `R-UI-01`, `R-SIM-01` -- owned by
`SPK-*`/`IMP-*`/`PUB-*`/`REL-*` tasks already `Verified` or explicitly
scheduled later) or are the four Bonus risks (`R-BON-*`), correctly
isolated as `Deferred bonus` and unaffected by `G5`.

Every `HRD-*`-named risk above now has real evidence from a real, verified
cycle; none required broadening beyond the concretely identified gap the
naming and existing coverage produced (`HRD-01`/`03`/`04`/`05`'s own review
docs already document each cycle's own explicit remaining boundary --
compression-bomb defense, live-representative-corpus measurement, and so
on -- as accepted limitations, not silently dropped scope).

## Verification

393 tests across the whole offline suite (Django application tests plus
`scripts/tests`, `research/planning`, and all three `evals/` suites) and
every offline verifier (`score_run.py`, `score_selection.py`,
`verify_candidate.py`, `score_similarity.py`, `compare.py`,
`check_plan.py`) pass on one committed state (`ea710ce`), confirming the
combined suite `HRD-06` itself is scoped to produce. This closes `HRD-06`:
every critical risk named against an `HRD-*` task has real evidence, the
offline suite runs together and green on one state, and live/API checks
remain explicitly separate. `HRD-06` moves to `Verified`; `G5` closes on
this report plus the accumulated `HRD-01`–`HRD-05` evidence it links.
