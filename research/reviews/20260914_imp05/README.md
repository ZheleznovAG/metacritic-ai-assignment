# IMP-05 dated browser probes

These are observations for `IMP-05` / `AC-UI-01`–`AC-UI-06` / `R-UI-01`, not
application tests or new CI gates. The report is
[imp_05_revalidation.md](../../../docs/requirements/imp_05_revalidation.md).
The public oracle is a frozen 2026-09-14 DB snapshot; a later live catalog may
legitimately differ. Do not treat a mismatch as an application defect without
checking current DB state.

`fixture_preview.py` creates a unique PostgreSQL test database using the checks
role from the ignored `.env.app`, populates nine synthetic games through existing
test helpers, and serves the application on loopback port 18765 with read-only
transactions. Real source/provider calls are replaced by fakes. On a stop marker
or normal interruption, the database is torn down in `finally`.

Reproduce from the repository root, sequentially with other DB checks:

```powershell
.\.venv-app\Scripts\python.exe -B scripts/check.py
# Ensure .artifacts/imp05-revalidation/ui-preview.stop is absent before starting.
.\.venv-app\Scripts\python.exe -B research/reviews/20260914_imp05/fixture_preview.py
```

In a second terminal, use the existing research environment with Playwright and
its Chromium installed (the dated run used Chromium 151.0.7922.34). Playwright
is a one-off research dependency, not an application lockfile change:

```powershell
.\.venv\Scripts\python.exe -B research/reviews/20260914_imp05/browser_probe.py fixture
New-Item -ItemType File .artifacts/imp05-revalidation/ui-preview.stop
```

`browser_probe.py public` reads the private preview host from `.env`, accesses
the preview directly without SSH forwarding and compares it to the published
DB snapshot. It only performs GETs and one deliberately rejected POST to the
read-only index. The report and errors omit private access data. It writes
dated screenshots under `docs/evidence/` and raw reports under `.artifacts/`;
preserve the original evidence when making a later observation.

`public_snapshot.py` is a remote read-only script, run via the existing trusted
SSH connection with `python3 -`. It invokes Python inside the web container and
prints only catalog data, summary metadata, selected source hashes, image ID and
health. It does not print Docker environment/connection settings or review text.
All live commands remain separate from deterministic CI.
