# Metacritic AI Assignment

Take-home assignment for the AI Automation Engineer position.

The application includes a read-only game catalog, platform filters and title search, hourly Metacritic discovery (`scripts/run_scheduler.py`), review collection and separate critic/user AI summaries (`scripts/run_worker.py`). Recommendations are **not implemented yet**. Current task and correction status is tracked in [action_plan.md](action_plan.md); scope and estimates are in [implementation_plan.md](implementation_plan.md). The [2026-09-12 audit](docs/requirements/implementation_audit_2026_09_12.md) records defects in repeated processing and summary handling; a passing local suite does not close them.

## Local development

Prerequisites: Docker Engine with Compose 2.24.4+ and uv **0.12.11** (`python -m pip install uv==0.12.11` if needed). The exact application interpreter is Python **3.12**; uv can download it. Keep the existing research `.venv` untouched: application commands use `.venv-app`.

From a fresh checkout in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = '.venv-app'
python -m uv sync --locked --python 3.12
.\.venv-app\Scripts\python.exe -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')"
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

The container suite uses canonical Linux/Python 3.12 and PostgreSQL 16. Tests run on an internal network without SSH/Groq credentials; dependency and tokenizer vocabulary downloads happen at build time. Both image targets include the hash-checked tokenizer vocabulary in `TIKTOKEN_CACHE_DIR=/opt/app/tokenizer-cache`; the runtime reads it as a non-root user on a read-only filesystem. Local setup downloads the same vocabulary explicitly before checks. The checks image also includes `evals/reviews`, `evals/review_selection` and `evals/similarity`.

The [similarity oracle](evals/similarity/metric.md) has separate offline checks, also run by `scripts/check.py` and CI:

```powershell
.\.venv-app\Scripts\python.exe -B evals/similarity/score_similarity.py --verify
.\.venv-app\Scripts\python.exe -B -m unittest discover -s evals/similarity -p "test_*.py" -v
```

Integrity checks do not select a similarity policy or imply owner acceptance; its current decision is recorded in [the action plan](action_plan.md).

`--profile app up` provisions the database roles, applies migrations using the schema-owner role, then starts web and Caddy. [CI workflow](.github/workflows/ci.yml) repeats build, offline runtime tokenization, checks and an actual Caddy HTTP/CSS smoke on a dedicated project with an initially empty database; it validates both CI and production Compose overrides. Whitespace is checked between the event's base/head commits, or in the selected commit for manual/initial runs. CI never deploys or calls live Metacritic/AI. A workflow file alone is not a successful CI run.

The runtime's offline check can also be run after a local build (substitute the image tag if `APP_IMAGE` is set):

```powershell
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges --workdir /opt/app/app metacritic-imp01:local python -B -c "from reviews.selection import count_tokens; assert count_tokens('Hello world') == 2"
```

Preview: [http://127.0.0.1:18081](http://127.0.0.1:18081). `/health/live/` checks the process; `/health/ready/` executes a bounded PostgreSQL query and returns generic 503 on failure. Neither endpoint reports hostnames, credentials or exception text. Web runs non-root with a read-only filesystem, bounded temporary storage and two Gunicorn workers. Caddy terminates the current **HTTP-only preview**; trusted TLS/hostname remain mandatory before G6. No login, admin or mutating endpoint exists.

Stop only this project, preserving its data: `docker compose --env-file .env.app --profile app down`. Do not use `down -v` in deployment or remove named volumes. Existing unrelated project containers are not part of this setup.

## Deployment boundary

[compose.production.yaml](compose.production.yaml) accepts a prebuilt versioned `APP_IMAGE`, publishes only Caddy on port 18081 and keeps PostgreSQL internal. A new preview environment can use `python3 scripts/init_env.py --production --host <public-host> --version <build-version>`; this is not a TLS production setup. Never overwrite an existing environment or reset a database password during a redeploy. Use the same project name and volumes for persistence.

Set `APP_VERSION` before building: Docker writes it into `app/build-version.txt` and the image label. Runtime environment values cannot override the HTTP build identity; a source checkout reports `local`. Choose a source commit or frozen source-snapshot identifier, not the resulting image ID. Record the full image ID separately and use `scripts/verify_image.py` before startup and against the running container, followed by the HTTP/CSS smoke. Changing a deployment's environment cannot turn an old image into a new release.

[IMP-01 revalidation](docs/requirements/imp_01_revalidation.md) records the scaffold deployment and permissions. [IMP-02 revalidation](docs/requirements/imp_02_revalidation.md) records the subsequent public upgrade to source `92c846a`, hosted CI, retained-score provenance correction and a real Elden Ring card at `/games/1/`: five platforms, verified fields/scores and two pending AI summaries. Follow the [deployment procedure](deploy/README.md) for subsequent upgrades. Scheduler and worker management commands exist in the application image; their permanently supervised Compose services remain part of `PUB-01`.

## Baseline and research evidence

[IMP-05 revalidation](docs/requirements/imp_05_revalidation.md) records public list/filter/card checks and the long-title layout correction. Its [dated browser probes](research/reviews/20260914_imp05/README.md) document reproduction with an isolated PostgreSQL fixture database and separate live preview checks; they are research evidence, excluded from deterministic CI.

- [Assignment](assignment.md), [requirements and acceptance](docs/requirements/acceptance.md).
- [Architecture](docs/decisions/0001-minimal-stack-and-architecture.md), [data and processing contracts](docs/design.md).
- [Published AI baseline](evals/reviews/baseline/README.md): saved synthetic inputs/outputs and original scoring, independently inspectable without another API call.
- [PLN-02 review and verification](docs/requirements/pln_02_review.md): contract corrections, PostgreSQL probe and remaining implementation limitations.
- [G3 planning review](docs/requirements/g3_review.md): coverage, dependency audit, workload/reserve and explicit limitations.
- [Implementation review of `6551e42`](docs/requirements/implementation_audit_6551e42.md): findings, requirement mappings and correction exit criteria; [archived probes and observations](research/reviews/6551e42/README.md). Current correction statuses and the next cycle belong to [action_plan.md](action_plan.md).

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
