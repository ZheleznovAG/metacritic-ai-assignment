# Metacritic AI Assignment

Take-home assignment for the AI Automation Engineer position.

The application includes a read-only game catalog, platform filters and title search, hourly Metacritic discovery (`scripts/run_scheduler.py`), review collection and separate critic/user AI summaries (`scripts/run_worker.py`). Cards show up to five similar saved games using the [genre policy](docs/decisions/0002-genre-similarity-policy.md), with shared genres and links that retain the search/filter context. The selected bonus scope ([ADR-0002](docs/decisions/0002-bonus2-scope.md)) adds public [operational monitoring](#service-activity-bon-21) and a [protected manual-run trigger](#manual-run-bon-22). [Integration evidence](docs/requirements/sim_ver_01_review.md) records verification and limitations. **Live public deployment and a full requirement→evidence index are in [Deployment boundary](#deployment-boundary)/[docs/evidence.md](docs/evidence.md).** Current task and correction status is tracked in [action_plan.md](action_plan.md); scope and estimates are in [implementation_plan.md](implementation_plan.md). The [2026-09-12 audit](docs/requirements/implementation_audit_2026_09_12.md) records historical defects in repeated processing and summary handling, since closed by the corrections it links; a passing local suite alone does not close a finding like that, only the corresponding fix and re-verification does.

## Local development

Prerequisites: Docker Engine with Compose 2.24.4+ and uv **0.12.11** (`python -m pip install uv==0.12.11` if needed). The exact application interpreter is Python **3.12**; uv can download it. Keep the existing research `.venv` untouched: application commands use `.venv-app`.

From a fresh checkout in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-app'
python -m uv sync --locked --python 3.12
.\.venv-app\Scripts\python.exe -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')"
.\.venv-app\Scripts\python.exe -m playwright install chromium
.\.venv-app\Scripts\python.exe scripts/init_env.py
docker compose --env-file .env.app up -d --wait db
.\.venv-app\Scripts\python.exe scripts/provision_db.py
.\.venv-app\Scripts\python.exe scripts/migrate.py
.\.venv-app\Scripts\python.exe app/manage.py collectstatic --noinput
.\.venv-app\Scripts\python.exe app/manage.py runserver 127.0.0.1:8000
```

`init_env.py` refuses to overwrite an existing `.env.app`. It generates distinct random credentials for provisioning, web, migrations, checks, scheduler and worker without printing them. Keep operator SSH/Groq settings in `.env`; neither `.env` nor `.env.app` enters the Docker build context. Compose passes only each service's required credentials. On Windows, protect both files with the account's filesystem ACLs; POSIX creation uses mode 0600.

For a pre-review IMP-01 environment, run `.\.venv-app\Scripts\python.exe scripts/init_env.py --upgrade-scaffold` once, then `scripts/provision_db.py`. The explicit upgrade adds missing role settings and preserves the existing admin password, database name, ports and data volume. Provisioning can be repeated; unknown legacy product tables require a separate ownership migration. It does not reset the database. See [the upgrade procedure](deploy/README.md#upgrade-of-the-original-imp-01-preview).

Web has CONNECT/USAGE/SELECT only. The scheduler role (used by `scripts/run_scheduler.py`) and the worker role (used by `scripts/run_worker.py`) each have SELECT/INSERT/UPDATE but no DELETE and no DDL. The migration role owns the application schema; the checks role has CREATEDB and owns `<POSTGRES_DB>_checks`, with no connection permission to the application database. Administrative credentials are used only by the one-shot `db_setup` process. `scripts/check.py` selects the checks role/database locally and refuses production mode.

For an existing review database, apply all pending migrations with `scripts/migrate.py` before starting the updated web/worker. The audit series includes `reviews.0004–0006`, `summaries.0003` and `catalog.0005`: immutable review version backfill, durable dispatch preference, current corpus bindings and attempt metadata. Pause writers during the upgrade; IDs and history references are preserved. Historical incomplete collections, lost metadata and unknown attempt fields are not reconstructed. Existing summaries without a verified current binding appear stale until the next successful collection/build. See the [snapshot upgrade limits](docs/requirements/imp_04_snapshot_correction.md) and [correction evidence](docs/requirements/implementation_corrections_batch.md).

PostgreSQL is published only on loopback port **15432** locally. Override `POSTGRES_PORT` in `.env.app` if occupied/reserved; do not change Windows port reservations or another project's database. Production/CI overrides remove both this port and the local DB network.

## Verification and container preview

```powershell
.\.venv-app\Scripts\python.exe -B scripts/check.py
docker compose --env-file .env.app build web checks
docker compose --env-file .env.app run --rm checks
docker compose --env-file .env.app --profile app up -d --wait
.\.venv-app\Scripts\python.exe scripts/smoke.py http://127.0.0.1:18081 --version local
```

The first command runs format/lint/types, Django checks, migration drift, static build, PostgreSQL permission/integration tests, deployment-tool tests and offline research evidence checks. Run local/container suites sequentially: they create/drop `test_metacritic_checks`. The permission test creates and removes its own probe table in the development application's database. Never run tests against production. Formatting changes: `.\.venv-app\Scripts\python.exe -m ruff format app scripts`; lint-only: `.\.venv-app\Scripts\python.exe -m ruff check app scripts`; type-only: set `PYTHONPATH=app`, then `python -m mypy` in the application environment.

The same suite includes the `IMP-07` Playwright journey in `app/tests/test_e2e.py`.
It starts a real scheduler tick on fake external catalog data, collects paginated
reviews, creates both summaries through the real provider adapter with a mock HTTP
transport, then uses Chromium against a live Django server and the disposable
PostgreSQL test database. It checks search, platform-dependent Metascore ordering,
the full card, audience separation, summary provenance, similar-game navigation,
return context and empty results. It never seeds ready-made summaries or calls
Metacritic/AI. Browser requests are restricted to the local server and one supplied
cover fixture. Playwright is pinned in the dev lock; the existing research `.venv`
is not used or changed by these checks.

On Linux hosts, install the browser and its OS dependencies with
`.venv-app/bin/python -m playwright install --with-deps --only-shell chromium`.
The Docker checks target performs this at build time; the runtime image excludes
Playwright and browsers. CI executes the journey on the internal checks network.
Set `E2E_ARTIFACT_DIR` to a local output directory to retain list/card/mobile
screenshots from the deterministic journey.

Similar games use `similarity.text` (embedding + TF-IDF, [ADR-0003](docs/decisions/0003-text-hybrid-similarity.md);
games with a foreign or missing description are matched by title and genre, [ADR-0004](docs/decisions/0004-foreign-description-gate.md)).
The worker embeds games while idle and precomputes each game's neighbours with the reasons shown on the card; the web only reads them.
The ONNX model (`sentence-transformers/all-MiniLM-L6-v2`, about 90 MB) is baked into the Docker image at
build time. Outside production, the first local run downloads it into `FASTEMBED_CACHE_PATH` (or the
default cache); set that variable to a directory with the model to run the real-model test
(`tests.test_similarity_index.RealModelTests`), which is skipped otherwise. The image is about 700 MB
and the worker container is limited to 768 MB.

The container suite uses canonical Linux/Python 3.12 and PostgreSQL 16. Tests run on an internal network without SSH/Groq credentials; dependency and tokenizer vocabulary downloads happen at build time. Both image targets include the hash-checked tokenizer vocabulary in `TIKTOKEN_CACHE_DIR=/opt/app/tokenizer-cache`; the runtime reads it as a non-root user on a read-only filesystem. Local setup downloads the same vocabulary explicitly before checks. The checks image also includes `evals/reviews`, `evals/review_selection` and `evals/similarity`.

The [similarity oracle](evals/similarity/metric.md) has separate offline checks, also run by `scripts/check.py` and CI:

```powershell
.\.venv-app\Scripts\python.exe -B evals/similarity/score_similarity.py --verify
.\.venv-app\Scripts\python.exe -B evals/similarity/compare.py
.\.venv-app\Scripts\python.exe -B -m unittest discover -s evals/similarity -p "test_*.py" -v
```

Integrity checks do not select a similarity policy or imply owner acceptance; its current decision is recorded in [the action plan](action_plan.md).

The comparison command recomputes both methods against the frozen oracle and verifies the published [comparison report](evals/similarity/comparison_report.json), including source hashes. `--write` explicitly publishes a reviewed new report; normal checks never rewrite it. [IMP-06](docs/requirements/imp_06_review.md) documents the method and its limitations. Apply `scripts/migrate.py` before starting updated application code: `catalog.0006_game_genres` adds stored genres and provenance. Existing games start with unknown genres until a normal successful detail fetch supplies them; the migration does not fabricate a taxonomy.

`--profile app up` provisions the database roles, applies migrations using the schema-owner role, then starts web and Caddy. [CI workflow](.github/workflows/ci.yml) repeats build, offline runtime tokenization, checks and an actual Caddy HTTP/CSS smoke on a dedicated project with an initially empty database; it validates both CI and production Compose overrides. Whitespace is checked between the event's base/head commits, or in the selected commit for manual/initial runs. CI never deploys or calls live Metacritic/AI. A workflow file alone is not a successful CI run.

The runtime's offline check can also be run after a local build (substitute the image tag if `APP_IMAGE` is set):

```powershell
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --workdir /opt/app/app metacritic-imp01:local python -B -c "from reviews.selection import count_tokens; assert count_tokens('Hello world') == 2"
```

Preview: [http://127.0.0.1:18081](http://127.0.0.1:18081). `/health/live/` checks the process; `/health/ready/` executes a bounded PostgreSQL query and returns generic 503 on failure. Neither endpoint reports hostnames, credentials or exception text. Web runs non-root with a read-only filesystem, bounded temporary storage and two Gunicorn workers. **This local/CI container preview is always plain HTTP** (`deploy/Caddyfile`'s `auto_https off`, unaffected by anything below) -- see [Deployment boundary](#deployment-boundary) for the separately-deployed production instance's own, now-trusted, TLS. No login, admin or mutating endpoint exists.

### Service activity (BON-21)

Open `/ops/` from **Service activity** in the catalog. `/ops/status/` provides the
same public, read-only snapshot. The page polls once a second and shows scheduler
and review/AI worker observations, current core progress, today's unique games,
separate enrichment queues and the last 20 runs. All times are UTC. A completed
core run does not imply completed reviews or summaries; queue counts are jobs,
not games. `failed`/`unstable` jobs remain visible as outstanding work.

Each supervised process writes an independent heartbeat once a second, including
while its main thread waits for external HTTP. After three seconds without a
heartbeat it is shown as `stale`; an overdue operation and an expired processing
lease are separate observations. Monitoring never acquires or releases work.
Connection loss is shown after five seconds; the last snapshot stays visible,
and polling recovers automatically. Without JavaScript, use **Refresh now**.

`OPS_MONITORING_ENABLED=false` disables both endpoints, navigation and heartbeat
after the affected processes are restarted. Scheduled processing and enrichment
continue.

Migration `processing.0003` adds heartbeat and immutable run/batch membership.
On recovery, new runs resume their original at-most-20 candidates and count unique
candidate outcomes, with attempts counted separately. A pre-upgrade interrupted
run has no recorded batch membership: it closes with `legacy_batch_unavailable`
and observed counters; remaining daily work stays available to a later run.
Historical terminal rows are preserved without inventing missing history.

The normal `scripts/check.py`/CI suite includes PostgreSQL snapshot/recovery tests,
Chromium freshness/reconnect tests and a 10-observer load check against 10,000 runs
and 100,000 jobs. Set `E2E_ARTIFACT_DIR` to an output directory before the checks
to save desktop/mobile screenshots and browser/load timing reports. Tests use
controlled inputs and the disposable checks DB. Public deployment evidence and
the current acceptance state belong to [action_plan.md](action_plan.md).

### Manual run (`BON-22`)

An authorized operator can force one ordinary processing batch from `/ops/` without
waiting for the next hour, using the same lease/selector/quota machinery as the
scheduled tick -- not a second, parallel path. There is no self-registration or admin
UI: create a non-superuser account with the one permission this needs, once web is up,
using the schema-owner role (never prints the password anywhere this session/log reads):

```sh
docker compose --env-file .env.app --profile app run --rm --no-deps migrate python app/manage.py create_operator <username>
```

Sign in at `/ops/login/`; a signed-in account without `processing.trigger_run` sees the
page normally but no **Run processing** button, and a direct `POST /ops/run/` still gets
a JSON `403` regardless of whether the button was ever shown -- authorization is checked
on every request, not by hiding UI. A successful click returns a durable request ID and
polls its own status (`queued` → `claimed` → `completed`/`conflict`/`expired`) without
JS by redirecting to `/ops/?request=<id>`. Limits: one new request per 5 minutes and at
most 6 per rolling hour service-wide; a replayed idempotency key (double submit, reload,
retry) never spends that quota and always returns the same request. Five failed logins
within 15 minutes lock out that username and that client IP separately for the same
window, with one generic error message either way. Web's DB role stays otherwise
read-only: `scripts/grant_manual_run_access.py` names the handful of exact tables/columns
this needs (its own sessions, its own manual-run/login-throttle rows, the admission lock,
one `auth_user` column) explicitly, as a separate step after `migrate`, rather than
widening the existing blanket `SELECT`-only grant. [BON-22 review](docs/requirements/bon_22_review.md)
records the implementation, adversarial findings and public verification, including a
real manual run claimed and executed by the already-running production scheduler.

Stop only this project, preserving its data: `docker compose --env-file .env.app --profile app down`. Do not use `down -v` in deployment or remove named volumes. Existing unrelated project containers are not part of this setup.

## Deployment boundary

**Live public deployment: [https://v978670.hosted-by-vdsina.com/](https://v978670.hosted-by-vdsina.com/)**
(real trusted Let's Encrypt TLS, no login needed to browse). Kept running for as long as
the review is ongoing, with no fixed decommission date; `scheduler`/`worker` keep
processing real hourly windows the whole time. [docs/evidence.md](docs/evidence.md) maps
every requirement to the review/evidence document that verified it.

[compose.production.yaml](compose.production.yaml) accepts a prebuilt versioned `APP_IMAGE`, publishes Caddy on `18081` (loopback) plus `80`/`443` and keeps PostgreSQL internal. A new preview environment can use `python3 scripts/init_env.py --production --host <public-host> --version <build-version>`; that alone is HTTP-only, matching the original `IMP-01` preview. Since `PUB-01`, [deploy/README.md](deploy/README.md#enabling-trusted-tls-once-a-hostname-is-available) documents turning on real Let's Encrypt TLS once a hostname resolving to the host exists (`deploy/Caddyfile.production`, `DJANGO_ALLOWED_HOSTS`/`DJANGO_HTTPS=true`) -- this project's own deployed instance runs with it enabled. Never overwrite an existing environment or reset a database password during a redeploy. Use the same project name and volumes for persistence.

Set `APP_VERSION` before building: Docker writes it into `app/build-version.txt` and the image label. Runtime environment values cannot override the HTTP build identity; a source checkout reports `local`. Choose a source commit or frozen source-snapshot identifier, not the resulting image ID. Record the full image ID separately and use `scripts/verify_image.py` before startup and against the running container, followed by the HTTP/CSS smoke. Changing a deployment's environment cannot turn an old image into a new release.

[IMP-01 revalidation](docs/requirements/imp_01_revalidation.md) records the scaffold deployment and permissions. [IMP-02 revalidation](docs/requirements/imp_02_revalidation.md) records the subsequent public upgrade to source `92c846a`, hosted CI, retained-score provenance correction and a real Elden Ring card at `/games/1/`: five platforms, verified fields/scores and two pending AI summaries. Follow the [deployment procedure](deploy/README.md) for subsequent upgrades. Since `PUB-01`, `scheduler`/`worker` are permanently supervised Compose services (`restart: unless-stopped`, each under its own restricted DB role) alongside `web`, replacing the earlier manual `scripts/run_scheduler.py`/`run_worker.py` verification loop, and the deployed instance serves real trusted TLS (also `PUB-01`, once a hostname existed to obtain a certificate for). Host reboot and two consecutive application hourly windows are `PUB-02`; external unauthorized-user smoke over the resulting HTTPS URL is `PUB-03` -- see [action_plan.md](action_plan.md) for current status and evidence links.

## Operations

`python scripts/diagnose.py --run <id> | --game <id> | --job review|summary <id> | --backlog` prints one JSON report: a run's status/error/counts, a game's latest daily-candidate outcome and every review/summary job's own state, one job's own state/error/attempt history, or outstanding work across the whole pipeline (daily candidates, review jobs, AI summary backlog). `python scripts/storage_report.py [--disk-path <path>]` prints database/table sizes, WAL size where the role has permission to read it, disk headroom for the given path, and three overhead ratios that a naive unique-review count would miss: saved text versions per identity, repeated observations per review, and provider attempts per terminal AI job. Both run read-only under the same SELECT-only web role the public preview uses; neither can write. `docs/requirements/hrd_05_review.md` records what each report measures and why, and which live measurements (a representative-corpus storage forecast, real disk headroom) belong to `PUB-02` instead.

Secrets never reach a stored error or a log line: `groq_adapter._safe_api_error` redacts the operator's API key from any provider error body before it is stored, and `config/safe_logging.py`'s formatter never logs free-form exception or request text, only the exception type name. Untrusted source text (title/developer/description, AI-generated claim text) relies on Django's default template auto-escaping, never bypassed anywhere in `app/presentation` (`|safe`/`mark_safe` are absent from the whole app). Every mutation runs inside `transaction.atomic()`; a write failure for any reason, including storage exhaustion, rolls back cleanly with no partial data, the same guarantee `test_catalog_constraints.py` and `test_catalog_ingest.py::test_a_failure_creating_jobs_rolls_back_the_whole_transaction` already exercise for constraint violations.

## Baseline and research evidence

[IMP-05 revalidation](docs/requirements/imp_05_revalidation.md) records public list/filter/card checks and the long-title layout correction. Its [dated browser probes](research/reviews/20260914_imp05/README.md) document reproduction with an isolated PostgreSQL fixture database and separate live preview checks; they are research evidence, excluded from deterministic CI.

[SIM-VER-01](docs/requirements/sim_ver_01_review.md) records the public upgrade to source `408bd62`, migration `catalog.0006`, 292 application tests and 202 public browser checks. Normal live detail ingestion supplied shared genres for Elden Ring and Wo Long; their cards link to each other by saved ID. Other unknown-genre games show an empty state until ordinary ingestion refreshes them. [Similarity browser probes](research/reviews/20260914_sim_ver_01/README.md) reproduce fixture and public navigation checks.

- [Assignment](assignment.md), [requirements and acceptance](docs/requirements/acceptance.md).
- [Architecture](docs/decisions/0001-minimal-stack-and-architecture.md), [data and processing contracts](docs/design.md).
- [Published AI baseline](evals/reviews/baseline/README.md): saved synthetic inputs/outputs and original scoring, independently inspectable without another API call.
- [PLN-02 review and verification](docs/requirements/pln_02_review.md): contract corrections, PostgreSQL probe and remaining implementation limitations.
- [G3 planning review](docs/requirements/g3_review.md): coverage, dependency audit, workload/reserve and explicit limitations.
- [Implementation review of `6551e42`](docs/requirements/implementation_audit_6551e42.md): findings, requirement mappings and correction exit criteria; [archived probes and observations](research/reviews/6551e42/README.md). Current correction statuses and the next cycle belong to [action_plan.md](action_plan.md).
- [Mandatory-scope audit, 2026-09-18](docs/requirements/main_audit_2026_09_18.md): assignment coverage, boundary findings, full deterministic checks and separate live observations; [reproduction commands and evidence](research/reviews/20260918_main/README.md). These historical defect-confirming probes are excluded from application tests and CI gates.

AI-history delivery (`REL-03` / `DEL-03`): [scope and privacy review](docs/requirements/rel_03_review.md),
[session-to-Git selection](docs/evidence/ai-history-selection.json), and
[archive manifest](docs/evidence/ai-history-audit.json). The archive stays under ignored
`.artifacts/rel03-ai-history/`. Rebuild with the two local session stores and an ignored
private JSON file containing `values` (credential/PII strings) and optional `usernames`:

```powershell
.\.venv-app\Scripts\python.exe -B scripts/export_ai_history.py --codex-root "$env:USERPROFILE/.codex/sessions" --claude-root "$env:USERPROFILE/.claude/projects/<project-session-directory>" --private-values .artifacts/rel03-ai-history/private-values.json --selection docs/evidence/ai-history-selection.json --output .artifacts/rel03-ai-history/ai-history.zip --report docs/evidence/ai-history-audit.json
.\.venv-app\Scripts\python.exe -B scripts/verify_ai_history.py --archive .artifacts/rel03-ai-history/ai-history.zip --audit docs/evidence/ai-history-audit.json --selection docs/evidence/ai-history-selection.json --private-values .artifacts/rel03-ai-history/private-values.json --report docs/evidence/ai-history-verification.json
.\.venv-app\Scripts\python.exe -B -m unittest scripts.tests.test_ai_history -v
```

Update the reviewed selection before adding new conversations. No credentials or
account stores belong in Git or the ZIP. These fixture-only tests also run through the
existing `scripts/check.py`/CI script-test discovery; exporting real logs is local only.

Offline evidence checks from the repository root with Python 3.12 or later (standard library only; no API key or `.env` needed):

```powershell
python -B evals/reviews/score_run.py evals/reviews/baseline/run.json --verify
python -B -m unittest discover -s evals/reviews -p "test_*.py"
python -B research/planning/check_plan.py
python -B -m unittest discover -s research/planning -p "test_*.py"
```

These commands verify research evidence and the planning baseline, not a working application. Token-budget and optional live checks are documented separately in [evals/reviews](evals/reviews/README.md).

To reproduce the historical `6551e42` audit after the local PostgreSQL setup above:

```powershell
.\.venv-app\Scripts\python.exe -B research/reviews/6551e42/reproduce.py
```

Run sequentially with other database tests. The probe uses the checks role and Django's test database, with fake source/provider calls. Its assertions deliberately reproduce defects on the reviewed implementation; successful corrections should make the corresponding assertions fail. It is archived evidence, excluded from deterministic CI acceptance. Each correction adds desired-outcome regressions to `app/tests/`, already run by local/container/CI `scripts/check.py`.
