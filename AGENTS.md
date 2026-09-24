# Repository Guidelines

## Project Structure & Sources of Truth

This repository has established its implementation baseline through `PLN-03` / `G3`. Ingestion, scheduling, review collection, AI summaries, the search/filter list and similarity card integration are implemented. Current verification and correction statuses belong only to `action_plan.md`.

- `assignment.md` is the primary specification.
- `methodology.md` defines the evidence-driven delivery process.
- `action_plan.md` is the workflow and task/gate tracker.
- `implementation_plan.md` contains task scope, expected verification outcomes, decomposed estimates and Requirement/Risk mappings; it does not duplicate current statuses or dependencies.
- `intake.md` captures the assignment baseline.
- `docs/requirements/` contains context, requirements, assumptions, acceptance criteria, and gate reviews.
- `docs/decisions/` contains accepted architecture decision records.
- `docs/design.md` defines accepted internal contracts, PostgreSQL data ownership, and processing invariants.
- `docs/risks.md` is the prioritized risk register.
- `evals/reviews/baseline/` contains the published sanitised AI run and original scorecard; its offline verifier and integrity tests are research tooling, not application tests.
- `evals/review_selection/` contains the frozen review-selection oracle, baseline and production-candidate verifier.
- `evals/similarity/` contains the similarity golden set, metric, frozen contract and evaluator integrity tests; owner acceptance belongs to `action_plan.md`.
- `research/methodology/` preserves prompts and exploration; it is evidence, not a requirements source.
- `research/planning/` contains the offline baseline audit and its negative-control tests; these are planning evidence, not application tests.
- `research/reviews/` preserves dated implementation-audit probes, observations and verification excerpts; defect-confirming probes are historical evidence, not application acceptance tests or CI gates.
- `app/config/` contains Django settings, routes, WSGI and sanitised logging; `app/presentation/` contains the read-only preview and health endpoints; `app/tests/` contains application checks on PostgreSQL 16.
- `app/tests/test_e2e.py` runs the mandatory processing-to-browser journey with pinned Playwright/Chromium and controlled external inputs from `app/tests/e2e_scenario.py`; it is part of the normal application suite and uses a disposable checks database.
- `app/metacritic/` contains external adapters/parsers; `app/catalog/` owns game data; `app/processing/` owns hourly discovery and daily progress; `app/reviews/` owns review collection/corpora; `app/summaries/` owns provider attempts and summaries.
- `app/processing/heartbeat.py`, `monitoring.py` and `progress.py` provide process observations and consistent read-only run/queue snapshots; `app/presentation/monitoring.py` and its template/JS expose `/ops/`. Monitoring never controls work ownership; frozen `RunCandidate` membership preserves batch progress after recovery. `app/tests/test_monitoring*.py` and `test_process_heartbeat.py` cover PostgreSQL, browser, recovery and bounded-load behavior.
- `app/similarity/` contains the versioned pure ranking policy over saved catalog features; it has no ORM, HTTP or provider dependencies. `evals/similarity/compare.py` reproduces the candidate/baseline comparison against the frozen oracle. `app/similarity/text.py` is the running `text-hybrid` policy (numpy, pure) and `embedder.py` its model wrapper; `app/catalog/similarity_index.py` is the worker-side upkeep (embeddings and precomputed `GameNeighbors`, read-only for web). `evals/similarity/text_labels.json`, `score_text.py` and `text_report.json` hold the real-catalogue comparison ([ADR-0003](docs/decisions/0003-text-hybrid-similarity.md)); `text_labels_v2.json`, `text_comparison_v2.md` and `text_report_v2.json` hold the second, pre-registered set behind policy 3.0.0 ([ADR-0004](docs/decisions/0004-foreign-description-gate.md)); the snapshot stays outside Git.
- `app/processing/admission.py` (durable manual-run idempotency/rate limiting, under the `TriggerAdmission` singleton lock) and `app/processing/dispatcher.py` (a `Heartbeat`-style background thread that claims queued `ManualRunRequest`s, sub-second of the hourly tick) extend `app/processing/scheduler.py`'s `run_manual` -- the same lease/resume/execute/close machinery as `run_tick`, not a parallel implementation. `app/presentation/operators.py` and its templates add login/logout/the `/ops/run/` trigger; standard `django.contrib.auth`/DB sessions provide accounts. `scripts/grant_manual_run_access.py` (run after `migrate`, unlike `provision_db.py`) names web's few narrow writes (its own sessions, its own manual-run rows, the admission lock, its own login-throttle rows, one `auth_user` column) explicitly, never widening the existing blanket read-only grant. `app/tests/test_admission.py`, `test_manual_run*.py` and `test_operators_*.py` cover the HTTP contract, PostgreSQL concurrency and browser flows; `scripts/tests/test_database_roles_manual_run.py` covers the new grants.
- `scripts/` contains environment initialization/upgrade, database role provisioning, migrations, image identity verification and HTTP/CSS smoke commands; `scripts/tests/` verifies permission boundaries and deployment counterexamples.
- `scripts/export_ai_history.py` exports the locally reviewed conversation selection for `REL-03` / `DEL-03`; `scripts/verify_ai_history.py` independently checks the attachment. `scripts/tests/test_ai_history.py` covers scope and privacy counterexamples with invented data. `docs/evidence/ai-history-*.json` holds selection and sanitised verification metadata; raw sessions, private-value files and the resulting ZIP stay outside Git under `.artifacts/`.
- `Dockerfile`, `compose*.yaml` and `deploy/` define immutable builds and isolated local/CI/preview deployment; `.github/workflows/ci.yml` runs deterministic checks, never deployment.

Add source and test directories only after `PLN-01–PLN-03` establish the implementation baseline. Document their layout here when introduced.

## Build, Test, and Development Commands

The stack is selected in `docs/decisions/0001-minimal-stack-and-architecture.md`. Use Python 3.12 in `.venv-app`; preserve the existing research `.venv`. Setup, lock, build and local/container verification commands are in `README.md`. Current repository checks include:

```powershell
git status --short          # inspect pending changes
git diff --check            # detect whitespace errors
rg --files                  # inventory tracked/worktree files
rg -n "RUN-01|AC-RUN-01" . # trace requirement and acceptance IDs
python -B evals/reviews/score_run.py evals/reviews/baseline/run.json --verify
python -B -m unittest discover -s evals/reviews -p "test_*.py"
python -B research/planning/check_plan.py
python -B -m unittest discover -s research/planning -p "test_*.py"
.\.venv-app\Scripts\python.exe -B scripts/check.py
docker compose --env-file .env.app run --rm checks
```

When tooling is added, expose reproducible commands in `README.md` and CI for setup, formatting, linting, tests, build, and local execution.

## Documentation Style & Naming

Use UTF-8 Markdown with LF line endings (`.gitattributes` enforces LF). Keep headings descriptive, paragraphs short, and tables focused. Use repository-relative links. Preserve stable identifiers such as `DATA-01`, `AC-DATA-01`, `ASM-10`, and `R-EXT-01`; update every traceability reference if an identifier changes. Prefer lowercase filenames, using underscores for top-level workflow documents and established directory conventions elsewhere.

## Testing & Evidence

Every change must reference a requirement, risk, or workflow task and state how it was verified. Follow `docs/requirements/acceptance.md`. Deterministic CI must use fixtures/fakes rather than live Metacritic or paid AI calls; keep live contract checks separate. A task is complete only when its evidence exists and its status is updated accurately.

A document being authored is not sufficient evidence for its own substantive claims. Before marking a task `Verified`, map every exit criterion to an independent artifact, executable check, or explicitly accepted limitation. If required evidence belongs to a future task, keep the current decision `Proposed` or `Candidate`; do not mark it `Accepted` and do not mark the task `Verified`.

For ranking, recommendation, AI-quality, or other heuristic decisions, freeze representative examples or a golden set, the metric, the acceptance threshold, and hard invariants before selecting or tuning the method. For external list or review ingestion, verify pagination or cursor behavior, ordering, exhaustion, duplicates, reported-versus-fetched counts, and worst-case volume before freezing the data contract. Enforce provider limits in provider units such as tokens, requests, and time, and verify the production maximum; character or item caps alone are not verification evidence.

## Commits & Pull Requests

Use focused Conventional Commits, matching history: `docs(risks): add prioritized risk register`, `research: add methodology exploration`, or `chore: normalize line endings`. Commit one completed task or coherent correction at a time.

PRs should identify task and requirement IDs, summarize decisions, list verification commands/evidence, and disclose changed assumptions or residual risks. Include screenshots for UI changes. Never include secrets, tokens, private access data, or unsanitized AI transcripts.

## Agent Workflow

Follow `action_plan.md` dependencies using one cycle: **one task → author → adversarial review → verify → one focused commit → stop**. The review must check requirements, acceptance criteria, risks, counterexamples, boundary conditions, and missing evidence. Unresolved material findings prevent `Verified`. Never begin the next task, skip gates, mark unverified work complete, or start Bonus before `G6`.

For hosted CI, a candidate commit may record an unfinished task with its accurate status. After an authorized push, record the CI run URL and tested SHA in a focused evidence commit; CI also checks that commit. A candidate or locally verified correction does not imply task completion. When a cycle is paused by external input, one independent Ready task may be taken as a separate cycle; the blocked task remains Blocked.

Keep `action_plan.md` as a concise task, dependency, status, gate, and evidence tracker—not as the detailed implementation specification. Put architecture decisions in ADRs, data and interface contracts in design documents, exploratory observations in `research/`, and examples, datasets, metrics, and thresholds in `evals/` or test artifacts. Link those artifacts from the plan instead of duplicating their content.

When a task requires human input, explicitly record it as `Blocked` / `Ask`, immediately ask the user one concrete question, and state the `needed-by` gate. Until the answer arrives, work only on tasks that are independent of that input; if none are available, stop and wait for the user's decision.
