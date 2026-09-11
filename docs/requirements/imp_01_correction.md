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
- Not verified in this pass: a hosted CI run, a clean-checkout Docker build, and redeployment to the VDS. The remote push permission remains the open `Ask`. (Resolved afterward: see Hosted CI and Corrected candidate redeployed to VDS below.)

## Adversarial review and remaining boundaries

The verification must cover failed writes by web, application/checks DB isolation, stale image rejection, runtime version override, fresh setup and repeated legacy upgrade. Schema ownership changes do not delete tables; unknown legacy product tables are refused. Passwords are omitted from tool output and password-bearing provisioning statements are excluded from PostgreSQL error-statement logging.

Evidence-file existence is a structural check, not an assessment of its substantive truth. External evidence URL availability remains an explicit human/live review boundary. Fixture tests use in-memory hypothetical statuses and never mark real tasks Verified.

The original [public preview evidence](imp_01_review.md) describes an earlier image. The VDS has not been updated by this correction.

## Hosted CI

Push access to `github.com/ZheleznovAG/metacritic-ai-assignment` was granted after this correction was authored. Commit `7a04706` (this correction) triggered the first-ever hosted run, [run 34573424815](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34573424815), which failed the whitespace step: `git diff --check` now examines the actual event range for the first time against the full previously-unpushed history, and flagged the two-trailing-space CommonMark hard breaks used throughout `assignment.md` and `research/methodology/**/*.md`, plus a genuine stray trailing space on `.gitattributes:1` and a blank line at EOF in `docs/requirements/g1_review.md:83`. Commit `e17c5f8` fixed the two real defects and scoped the whitespace attribute to stop flagging intentional markdown hard breaks (`*.md whitespace=-blank-at-eol`), while keeping `blank-at-eof`/`space-before-tab` checks active.

[Run 34573629767](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34573629767) at `e17c5f8` passed in full: whitespace/Compose validation, locked runtime/checks build, image-identity recording, offline verification on PostgreSQL 16 (including the live database-role permission boundaries), the actual Caddy-fronted runtime start and the external HTTP/CSS smoke.

Recording that result in evidence (commit `490dbdd`, docs only) exposed a second, unrelated defect: `research/planning/test_check_plan.py::test_mandatory_task_cannot_be_dropped` located its fixture row by matching the literal substring `"| base | Blocked |"` in the live `action_plan.md`, which only existed because IMP-01 happened to be `Blocked`; moving IMP-01 to `In progress` removed that substring and broke the test's own setup assertion ([run 34573938175](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34573938175) failed). The rule under test does not require a `Blocked` starting point, so commit `6d29461` retargeted the fixture to `"| base | Verified |"` (the G0-G3 rows, permanently `base`/`Verified` by this project's baseline history), decoupling the negative control from whichever task happens to be `Blocked` on a given day. [Run 34574112620](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34574112620) at `6d29461` passed in full.

## Corrected candidate redeployed to VDS

Built `metacritic-imp01:6d29461` from the hosted-CI-verified commit `6d29461066022cf94e58f605604c453be27e7640` (`docker build --target runtime --build-arg APP_VERSION=<sha>`); local image ID `sha256:187fee885f403a51fe85ed8f1de47729378197eb44f715d0ef644d30d3bce13b`. Exported and packaged per [deploy/README.md](../../deploy/README.md); both archive SHA-256 values (image `54fac3e0...a3d66b`, config `fcfed4b7...54c1a0`) matched after transfer to the existing `metacritic-ai-assignment-imp01` deploy directory, before extraction/import.

Followed the documented upgrade procedure: `docker load`, `verify_image.py` on the loaded image, `scripts/init_env.py --upgrade-scaffold` (preserved `POSTGRES_PASSWORD` and the existing volume; appended the missing `WEB_DB_*`/`MIGRATE_DB_*`/`CHECKS_DB_*` settings the original scaffold's `.env.app` predated), then updated only `APP_IMAGE`/`APP_VERSION`.

While following the documented commands, `docker compose ... run --rm migrate` (without `--profile app`) failed with `no such service: db_setup`: `migrate` is `profiles: [ops]` and its `depends_on: db_setup` is `profiles: [app, checks]`, and Compose does not activate a dependency's profile just because the named service's own profile is active. This had never been exercised end-to-end before, since local development runs `provision_db.py`/`migrate.py` directly instead of through `docker compose run`. Fixed by adding `--profile app` to the documented command (`deploy/README.md`); with it, `db_setup` (idempotent; re-provisioning is documented as safe) and `migrate` both completed (`No migrations to apply`, as expected for the empty scaffold).

`docker compose --profile app up -d --wait` recreated only `web` (`db`/`caddy` images unchanged); all three containers reported `healthy`. `verify_image.py --container metacritic-imp01-prod-web-1` confirmed the running container's image ID and label match the built/loaded image. `smoke.py` passed all seven HTML/health/CSS assertions both from inside the VDS (loopback) and from the local development machine against the public host without an SSH tunnel. Resource snapshot: web 93.25 MiB/384 MiB (0.02% CPU), db 28.54 MiB/512 MiB, caddy 11.38 MiB/96 MiB; `/var/lib/docker` had 74,485,652 KiB free (6% used). The web container runs as UID/GID 65532:65532 with a read-only root filesystem, matching the local/CI evidence.

The previous image (`metacritic-imp01:9f65d829f248`) and its archives were left in place on the VDS for rollback; only the running `web` container was recreated, and the named PostgreSQL/Caddy volumes were not touched.

IMP-01's previously open criteria (permitted remote, authorized push/hosted CI, final source/image identity, public verification of the corrected candidate) are now all satisfied. What this pass has not done is an independent adversarial review of this deployment by anyone other than its author in the same session — the same limitation the original [public preview evidence](imp_01_review.md) cited for withholding `Verified` even after its own thorough self-review. `action_plan.md` records IMP-01 as `In progress`, not `Verified`, for that reason; the remaining step is that independent review, not further technical evidence.
