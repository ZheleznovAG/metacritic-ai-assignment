# Development and operations

Current entry point: [README](../README.md). This guide expands commands; acceptance
and task decisions remain in [action_plan.md](../action_plan.md).

## Environment

Use Python 3.12 in `.venv-app`; preserve the research `.venv`. Dependencies are locked
by uv 0.12.11. Docker Engine and Compose 2.24.4+ are required.

```powershell
python -m pip install uv==0.12.11
$env:UV_PROJECT_ENVIRONMENT = '.venv-app'
python -m uv sync --locked --python 3.12
.\.venv-app\Scripts\python.exe -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')"
.\.venv-app\Scripts\python.exe -m playwright install chromium
.\.venv-app\Scripts\python.exe scripts/init_env.py
```

`init_env.py` refuses to overwrite `.env.app`; credentials are distinct and never
printed. `.env*` stays outside Git/build context. For an original IMP-01 environment,
use `scripts/init_env.py --upgrade-scaffold` then provision roles; this preserves
credentials, ports and volumes. [Upgrade instructions](../deploy/README.md#upgrade-of-the-original-imp-01-preview).
Local PostgreSQL binds loopback 15432; change `POSTGRES_PORT` if occupied.

## Optional host Django development

Container checks are canonical. Host development requires accessible PostgreSQL:

```powershell
docker compose --env-file .env.app up -d --wait db
.\.venv-app\Scripts\python.exe scripts/provision_db.py
.\.venv-app\Scripts\python.exe scripts/migrate.py
.\.venv-app\Scripts\python.exe app/manage.py collectstatic --noinput
.\.venv-app\Scripts\python.exe app/manage.py runserver 127.0.0.1:8000
```

The checks role owns a disposable checks database and cannot connect to the app DB.
Permission tests require an unmigrated app database, so use README's isolated checks
project after starting the app. Do not run checks concurrently or against production.
`scripts/check.py` refuses production mode. Runtime excludes Playwright; checks install
pinned Chromium and use fake external inputs for the processing-to-browser journey.
Set `E2E_ARTIFACT_DIR` before checks to retain screenshots.

```powershell
.\.venv-app\Scripts\python.exe -m ruff format app scripts
.\.venv-app\Scripts\python.exe -m ruff check app scripts
$env:PYTHONPATH = 'app'
.\.venv-app\Scripts\python.exe -m mypy
.\.venv-app\Scripts\python.exe -B research/planning/check_plan.py
.\.venv-app\Scripts\python.exe -B evals/similarity/compare.py
```

`compare.py` verifies frozen source/report hashes, not current text-policy quality.
Real-model tests require `FASTEMBED_CACHE_PATH`; Docker includes the downloaded model
and tokenizer. Models/provider calls and original frozen evaluations are explained in
[PROJECT_STATUS](../PROJECT_STATUS.md) and their linked protocols.

## Operator and diagnostics

Create a non-superuser with `processing.trigger_run` using the migration role:

```powershell
docker compose --env-file .env.app --profile app run --rm --no-deps migrate python app/manage.py create_operator <username>
```

Sign in at `/ops/login/` and use **Run processing** on `/ops/`. Durable idempotency,
CSRF/permissions and service-wide limits apply: one new request per five minutes,
at most six per rolling hour. Failed-login throttles apply independently to username
and IP. [Full contract and implementation evidence](bonus2_design.md).

After a review-selection/contour upgrade, run `python app/manage.py refresh_summaries`
inside the worker container (`--dry-run` counts only). It rebuilds stale corpora from
saved reviews and queues missing summaries without refetching Metacritic; cards retain
stale results until regeneration. Apply migrations/grants before updated processes.

Read-only diagnostics: `python scripts/diagnose.py --backlog`, `--run <id>`,
`--game <id>` or `--job review|summary <id>`; storage: `python scripts/storage_report.py
[--disk-path <path>]`. [Measured properties](requirements/hrd_05_review.md).

Stop while preserving data: `docker compose --env-file .env.app --profile app down`.
Deployment and backup/restore commands belong to [deploy/README](../deploy/README.md).
Historical AI-history export commands and old upgrade observations are retained in
the [dated README archive](history/readme-20261005.md#baseline-and-research-evidence);
raw sessions, private values and attachments remain outside Git.
