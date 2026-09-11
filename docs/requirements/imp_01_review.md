# IMP-01: scaffold verification, pending external CI

Date: 2026-09-09; public deployment checked through 03:55 UTC, clean-source verification completed at 04:57 UTC. Task `IMP-01`; requirements `DEL-01`, `DEL-02`, `NFR-06`; risks `R-DEP-01`, `R-DEP-02`, `R-REP-01`, `R-SEC-01`, `R-TST-01`. Current status belongs to [action_plan.md](../../action_plan.md).

This is historical evidence for the original preview. The subsequent [tooling correction](imp_01_correction.md) changes DB credentials/ownership, build identity and verification. The original image/public smoke does not certify those changes.

## Exit-criterion audit

| Criterion | Independent evidence obtained | Remaining boundary |
|---|---|---|
| Reproducible runtime and lock | `uv.lock` resolved 20 packages; separate Python 3.12.14 environment; digest-pinned Python, uv, PostgreSQL and Caddy; successful clean-layer Docker build without operator files; final source snapshot built and started on a separate test project | A real fresh-checkout CI run is still needed; the source snapshot has no Git metadata and its build reused cached dependency layers |
| Format/lint/types/tests/build | Final `scripts/check.py` reruns passed locally on Windows/Python 3.12.14 and inside the clean-source Linux checks image: Ruff, mypy, Django checks, migration drift, static build, 7 application tests, 12 plan tests, 7 AI-evidence integrity tests and baseline verifier | This is executed local/container evidence, not a hosted CI result |
| Actual PostgreSQL backend | Application integration test checks PostgreSQL major 16 and UTC; readiness executes `SELECT 1`; no SQLite fallback | No product tables or runtime queue exist yet |
| Public versioned image | Archive checksums matched on VDS; image imported and launched as `metacritic-imp01:9f65d829f248`; web/DB/Caddy all healthy; seven HTTP smoke assertions passed both on VDS and from the local machine without SSH tunnel | HTTP-only scaffold, not G6 TLS or functional acceptance |
| Resource baseline | At startup: DB 23.72 MiB/512 MiB, web 85.2 MiB/384 MiB, Caddy 9.812 MiB/96 MiB; CPU 0.03%/0.01%/0.00%. Before deploy: 75,683,604 KiB disk available, 3,511,528 KiB RAM available | Empty-app snapshot, not throughput/storage-capacity evidence |
| Layout and commands documented | [README](../../README.md), [AGENTS](../../AGENTS.md), [deployment procedure](../../deploy/README.md) and [preview screenshot](../evidence/imp01-preview.png); container build/check/start/smoke commands exercised from the source snapshot | Hosted checkout and final source commit identity remain unverified |

The original research `.venv` was preserved; uv 0.12.11 was added as tooling, while application packages use `.venv-app`. No Metacritic or AI request was made. No application scheduler/worker is simulated: those entry points belong to later tasks.

## Artifact identity and public check

- Inspected local image ID: `sha256:9f65d829f24870ed029e698be52674ac81699088fa75c1d97b8e43a5c1f97862`; release tag suffix `9f65d829f248`. This is an image identifier, **not a source commit SHA**; source changes are not committed yet.
- Image archive SHA-256: `deed5d2b500725604ad692a4667e063439b6a30d31927e4a011f1e184a45f540`.
- Deployed configuration archive SHA-256: `a73e0236f5688f668cf770ec6961945c7a8b71bd3d325ff289c0eeff4e4d4c94`.
- Deploy path: `metacritic-ai-assignment-imp01` under the configured deploy account; Compose project `metacritic-imp01-prod`. New application-only secrets were generated on VDS; operator `.env` and keys were not transferred.
- Public URL is `http://<DEPLOY_SSH_HOST>:18081`; access metadata is not published in Git. The external smoke checked `/`, `/health/live/`, `/health/ready/` = 200 and `/.env`, `/.env.app`, `/admin/`, `/unknown` = 404. Both health payloads matched version `9f65d829f248` and the exact allowlisted fields.
- The screenshot is the same scaffold locally at 1280×800, showing version `local`; it is not represented as a screenshot of the VDS version.

## Adversarial review and corrections

| Finding / counterexample | Correction / verification |
|---|---|
| Docker startup alone can be mistaken for HTTP readiness | Separate process/DB endpoints, web readiness healthcheck, Caddy HTTP healthcheck and external smoke; Caddy restart failure was found before claiming success |
| `cap_drop: ALL` prevents executing the official Caddy binary | An isolated `getcap /usr/bin/caddy` returned `cap_net_bind_service=ep`; adding only `NET_BIND_SERVICE` fixed exec EPERM, then real HTTP passed |
| Flow-style YAML splits unquoted tmpfs options at commas | Quoted each tmpfs mount; actual container creation and healthchecks passed after correction |
| Default DB port lies in a Windows reserved range | `netsh` showed 55432 inside 55336–55435; changed only the new project's local port to 15432, without changing OS reservations |
| Docker Desktop cannot forward the host DB connection through this internal-only network | Local DB gained a routable local network; the exact local Python suite then passed. Production/CI overrides remove it and expose no DB port |
| Mocking the underlying Django connection method damages SimpleTestCase teardown | Mocked the adapter reference instead; all seven tests and teardown pass |
| Missing/unknown host, leaked DB error or public write endpoint | Tests verify rejected foreign Host, generic 503, safe log fields, 405 for POST and 404 for private/admin routes |
| Web could inherit operator credentials | Separate `.env.app`, explicit Compose environment, allowlisted Docker context and configuration-only deployment archive; no blanket operator env_file |
| Passing tests could falsely close CI/public/product acceptance | Hosted CI remains pending; product features, TLS and later gates are explicitly not claimed |

This is an adversarial self-review, not review by an independent person. The absent hosted CI/fresh-checkout result is a material missing exit criterion: IMP-01 must remain unverified.

Additional read-only verification: runtime reports UID/GID `65532:65532` and read-only root; operator/provider environment variable count is zero; `/opt/app/.env` and `/opt/app/.env.app` are absent in the running image. `check --deploy` emits exactly W004 (HSTS) and W008 (HTTPS redirect), with zero silenced checks: these are explicitly retained limitations of the read-only HTTP preview, not a TLS success claim. The Docker context also excludes nested `.env*` and `.secrets` paths.

## Clean-source verification

An allowlisted source archive was extracted into the new ignored `.artifacts/imp01-clean-source` directory. Archive SHA-256: `503d38e6c21f057447f92fdcfddb43ed45db0fbd2c21cf9778afcf3a7123858b`. The snapshot contains the application, build/configuration files and offline check inputs; it excludes `.env`, `.env.app`, virtual environments, generated static files and the owner's `metacritic.zip`. It is not a Git checkout or a complete delivery archive.

The verification used project `metacritic-imp01-clean`, `compose.ci.yaml`, public test-only credentials, a new PostgreSQL volume, runtime version `clean-source` and loopback HTTP port 18082. Commands below all exited zero:

```powershell
docker compose -f compose.yaml -f compose.ci.yaml config --quiet
docker compose -f compose.yaml -f compose.ci.yaml build web checks
docker compose -f compose.yaml -f compose.ci.yaml run --rm checks
docker compose -f compose.yaml -f compose.ci.yaml --profile app up -d --wait --wait-timeout 120
python -B scripts/smoke.py http://127.0.0.1:18082 --version clean-source
docker compose -f compose.yaml -f compose.ci.yaml --profile app down
```

All 26 tests passed; mypy checked 11 application files, Ruff checked 14 application/script files, and the saved AI baseline remained 96/98 without live calls. DB/web/Caddy became healthy; all seven external HTTP assertions passed with the expected version. Only temporary test containers/networks were removed after verification; named volumes and source/image archives were retained. Other local projects and the VDS preview were not changed by this run. Documentation of these results was updated afterward; runtime sources were unchanged.

## Reproduction and pending input

Use the [README commands](../../README.md#verification-and-container-preview). Container verification and local Python verification must run sequentially against their own development DB, never against production. [CI](../../.github/workflows/ci.yml) uses the same commands and an internal test network; it has no deployment credentials and never calls Metacritic/Groq.

**Ask, needed-by G4:** provide the permitted remote repository and authorize push/CI. At the date of this report, no remote or completion commit existed. The current protocol permits a candidate/correction commit while IMP-01 remains unverified. After an authorized push, record the hosted run URL and tested SHA in a focused evidence commit; CI also checks that commit. Only complete criteria close IMP-01. Independent Ready tasks may have separate cycles during the external wait; IMP-02 still requires verified IMP-01.

Reference documentation consulted: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/), [Compose startup health dependencies](https://docs.docker.com/compose/how-tos/startup-order/), [WhiteNoise integration](https://whitenoise.readthedocs.io/en/stable/django.html), [pinned checkout release commit](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1). These explain tooling choices; they do not substitute for project test evidence.
