# SIM-VER-01 browser observations

These dated probes support `SIM-VER-01` / `AC-SIM-01–03` / `AC-UI-06`.
They are research evidence, not application tests or CI gates. The deterministic
integration regressions live in `app/tests/test_similarity_integration.py`.

From the repository root, use the application environment for the server and
the existing research environment with Playwright/Chromium for the browser:

```powershell
.\.venv-app\Scripts\python.exe -B scripts/check.py
# Ensure .artifacts/sim-ver-01/preview.stop is absent before starting.
.\.venv-app\Scripts\python.exe -B research/reviews/20260914_sim_ver_01/preview.py
# In another terminal:
.\.venv\Scripts\python.exe -B research/reviews/20260914_sim_ver_01/browser_probe.py fixture
New-Item -ItemType File .artifacts/sim-ver-01/preview.stop
```

The preview creates a unique PostgreSQL test database with seven explicitly
synthetic games, serves the actual application on loopback port 18766 with
read-only transactions, and tears that database down on normal stop. No source
or provider calls occur. The browser checks every saved card against an
independent genre-set oracle and the fixture's explicit expected query IDs,
then actually clicks recommendation links and the return-to-results link.
The dated run uses Chromium 151.0.7922.34; browser setup remains a research
dependency and will be formalized with full E2E in `IMP-07`.

The `public` mode reads the private preview host from ignored `.env` and compares
all cards to a separately captured current DB snapshot at
`.artifacts/sim-ver-01/public-snapshot.json`. It only issues HTTP GETs, makes no
source/provider calls and writes reports without access metadata. Never use the
synthetic seed on the public database. A later changed catalog requires a new
snapshot rather than treating historical results as permanent expectations.

`public_snapshot.py` is a remote read-only script for `python3 -` over the
existing trusted SSH connection. It runs inside the web container with the
SELECT-only role and emits saved genres, provenance, ranking results and source
hashes. The raw JSON is copied to the snapshot path above before the browser run.
`refresh_genres.py` preserves the dated, explicitly scoped live ingestion of
existing IDs 1/13 after their first genre migration. Its preconditions describe
that historical initial state; it is not a generic repeatable backfill command.
It uses only the scheduler role and makes no AI calls. The public execution
occurred on 2026-09-15 after owner-authorized preview upgrade.

See [the review](../../../docs/requirements/sim_ver_01_review.md) for evidence,
limitations and the exact source/CI/public verification references.
