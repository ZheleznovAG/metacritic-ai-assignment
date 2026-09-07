# Repository Guidelines

## Project Structure & Sources of Truth

This repository is currently defining its implementation baseline; it does not yet contain application source, tests, or runtime assets.

- `assignment.md` is the primary specification.
- `methodology.md` defines the evidence-driven delivery process.
- `action_plan.md` is the workflow and task/gate tracker.
- `intake.md` captures the assignment baseline.
- `docs/requirements/` contains context, requirements, assumptions, acceptance criteria, and gate reviews.
- `docs/decisions/` contains accepted architecture decision records.
- `docs/risks.md` is the prioritized risk register.
- `research/methodology/` preserves prompts and exploration; it is evidence, not a requirements source.

Add source and test directories only after `PLN-01–PLN-03` establish the implementation baseline. Document their layout here when introduced.

## Build, Test, and Development Commands

The stack is selected in `docs/decisions/0001-minimal-stack-and-architecture.md`, but application tooling is not scaffolded until `IMP-01`. Current repository checks are:

```powershell
git status --short          # inspect pending changes
git diff --check            # detect whitespace errors
rg --files                  # inventory tracked/worktree files
rg -n "RUN-01|AC-RUN-01" . # trace requirement and acceptance IDs
```

When tooling is added, expose reproducible commands in `README.md` and CI for setup, formatting, linting, tests, build, and local execution.

## Documentation Style & Naming

Use UTF-8 Markdown with LF line endings (`.gitattributes` enforces LF). Keep headings descriptive, paragraphs short, and tables focused. Use repository-relative links. Preserve stable identifiers such as `DATA-01`, `AC-DATA-01`, `ASM-10`, and `R-EXT-01`; update every traceability reference if an identifier changes. Prefer lowercase filenames, using underscores for top-level workflow documents and established directory conventions elsewhere.

## Testing & Evidence

Every change must reference a requirement, risk, or workflow task and state how it was verified. Follow `docs/requirements/acceptance.md`. Deterministic CI must use fixtures/fakes rather than live Metacritic or paid AI calls; keep live contract checks separate. A task is complete only when its evidence exists and its status is updated accurately.

## Commits & Pull Requests

Use focused Conventional Commits, matching history: `docs(risks): add prioritized risk register`, `research: add methodology exploration`, or `chore: normalize line endings`. Commit one completed task or coherent correction at a time.

PRs should identify task and requirement IDs, summarize decisions, list verification commands/evidence, and disclose changed assumptions or residual risks. Include screenshots for UI changes. Never include secrets, tokens, private access data, or unsanitized AI transcripts.

## Agent Workflow

Follow `action_plan.md` dependencies using one cycle: **one task → verify → one focused commit → stop**. Never begin the next task, skip gates, mark unverified work complete, or start Bonus before `G6`.

When a task requires human input, explicitly record it as `Blocked` / `Ask`, immediately ask the user one concrete question, and state the `needed-by` gate. Until the answer arrives, work only on tasks that are independent of that input; if none are available, stop and wait for the user's decision.
