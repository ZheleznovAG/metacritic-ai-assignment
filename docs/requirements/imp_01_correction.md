# IMP-01 / PLN-03: tooling review correction

Date: 2026-09-11. Scope: the requested correction of agent workflow, Docker, deployment and documentation review findings. Links: `IMP-01`, `PLN-03`, `NFR-06`, `DEL-01`, `DEL-02`, `R-REP-01`, `R-SEC-01`, `R-TST-01`. Current task status remains in [action_plan.md](../../action_plan.md).

## Changes and independent checks

| Finding | Correction | Verification artifact |
|---|---|---|
| Hypothetical Bonus graphs rejected an accepted none/one-branch completion | An explicit current scope controls status checks; structural/budget checks retain all four graphs | [Plan negative controls](../../research/planning/test_check_plan.py): completed scopes, unaccepted scope and unfinished selected branch |
| Missing evidence and Dropped Must were accepted | Local evidence files must exist inside the repository; base tasks cannot be Dropped; optional drops require an accepted exclusion | Same executable negative controls |
| ADR contradicted environment separation; CI/commit and paused-task rules were ambiguous | ADR/README/AGENTS/tracker now use `.venv-app`, scoped `.env.app`, candidate/evidence commits and separate independent task cycles | Documentation diff and local link/consistency audit |
| Web held PostgreSQL administrative credentials | Separate web/migration/checks logins; one-shot provisioning, explicit environment mappings and application/checks DB permissions | [Actual PostgreSQL permission tests](../../scripts/tests/test_database_roles.py); existing-scaffold upgrade rehearsal |
| Runtime environment could falsify build identity | Build version is embedded in the image; loaded/running full image IDs are verified separately | [Image verifier](../../scripts/verify_image.py), [stale-container negative control](../../scripts/tests/test_tools.py), real runtime checks |
| Backup ZIP was eligible for Git staging | Exact `/metacritic.zip` ignore rule | `git check-ignore --no-index metacritic.zip` |
| CI whitespace command examined an empty working-tree diff | Event base/head or selected committed changes are checked; production Compose also validated | CI workflow and committed-whitespace counterexample |
| Smoke omitted static assets | Parse and fetch same-origin stylesheet links; require nonempty CSS with the correct media type | [Broken-CSS negative control](../../scripts/tests/test_tools.py) and Caddy HTTP/CSS smoke |

## Verification results

This correction is not a hosted CI or public deployment result.

- Plan negative controls: 18 tests passed, including none/bonus1/bonus2/both completion, missing evidence and excluded Must.
- A dedicated local project `metacritic-imp01-review` and new named volume were used. Its legacy `django_migrations` row survived two provisioning runs and transfer to the migration owner; local migration command passed. Original local/VDS data volumes were not used.
- Full local `scripts/check.py` (`.venv-app`, Python 3.12.14, PostgreSQL 16 container): Ruff format/check, mypy `--strict`, Django checks, migration drift, static build, 7 application tests (including the real PostgreSQL 16 readiness test), 5 `scripts/tests` (database-role permission boundaries, stale-container rejection, environment upgrade, CSS smoke negative controls), 18 planning tests and 7 AI-baseline integrity tests all passed; the saved baseline verifier reported 96/98.
- `scripts/tests/test_database_roles.py` executed against the live local PostgreSQL container after re-running `scripts/provision_db.py`: the web role has `rolsuper=false, rolcreatedb=false, rolcreaterole=false, rolreplication=false, rolbypassrls=false`, reads existing rows, and is rejected with `InsufficientPrivilege` on `INSERT`/`DROP`/`CREATE TEMP TABLE`; connecting to the checks database or with the raw admin credentials from the web role's context both fail.
- `scripts/smoke.py` executed against the already-running local `--profile app` stack (`http://127.0.0.1:18081`): all seven HTML/health assertions and the stylesheet fetch/content-type check passed.
- `docker compose --env-file .env.app -f compose.yaml -f compose.ci.yaml config --quiet` and the equivalent production override both validated without error.
- `git diff --check` reported no whitespace errors across the working tree.
- Not verified in this pass: a hosted CI run, a clean-checkout Docker build, and redeployment to the VDS. The remote push permission remains the open `Ask`.

## Adversarial review and remaining boundaries

The verification must cover failed writes by web, application/checks DB isolation, stale image rejection, runtime version override, fresh setup and repeated legacy upgrade. Schema ownership changes do not delete tables; unknown legacy product tables are refused. Passwords are omitted from tool output and password-bearing provisioning statements are excluded from PostgreSQL error-statement logging.

Evidence-file existence is a structural check, not an assessment of its substantive truth. External evidence URL availability remains an explicit human/live review boundary. Fixture tests use in-memory hypothetical statuses and never mark real tasks Verified.

The original [public preview evidence](imp_01_review.md) describes an earlier image. The VDS has not been updated by this correction.

## Hosted CI

Push access to `github.com/ZheleznovAG/metacritic-ai-assignment` was granted after this correction was authored. Commit `7a04706` (this correction) triggered the first-ever hosted run, [run 34573424815](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34573424815), which failed the whitespace step: `git diff --check` now examines the actual event range for the first time against the full previously-unpushed history, and flagged the two-trailing-space CommonMark hard breaks used throughout `assignment.md` and `research/methodology/**/*.md`, plus a genuine stray trailing space on `.gitattributes:1` and a blank line at EOF in `docs/requirements/g1_review.md:83`. Commit `e17c5f8` fixed the two real defects and scoped the whitespace attribute to stop flagging intentional markdown hard breaks (`*.md whitespace=-blank-at-eol`), while keeping `blank-at-eof`/`space-before-tab` checks active.

[Run 34573629767](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34573629767) at `e17c5f8` passed in full: whitespace/Compose validation, locked runtime/checks build, image-identity recording, offline verification on PostgreSQL 16 (including the live database-role permission boundaries), the actual Caddy-fronted runtime start and the external HTTP/CSS smoke.

IMP-01 still needs the corrected candidate redeployed to the VDS and re-verified externally (public image/source identity, HTTP/CSS smoke and resource baseline on the actual host); the current VDS preview still serves the pre-correction image. A locally verified correction commit and a green hosted CI run do not by themselves close IMP-01 or start IMP-02.
