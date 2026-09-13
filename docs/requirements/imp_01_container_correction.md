# IMP-01: container reproducibility correction after IMP-04

Opened: 2026-09-12; verification completed: 2026-09-13 (Asia/Novosibirsk).
Scope: `IMP-01`, `NFR-06`, `R-REP-01`, `R-TST-01`, `R-SEC-01`.
Current task status belongs only to [action_plan.md](../../action_plan.md).
The [implementation audit](implementation_audit_2026_09_12.md) separates these regressions from
application defects that require subsequent focused cycles.

## Changes

- Include `evals/review_selection` in the Docker build context and checks image.
- Download the locked tiktoken package's hash-verified `o200k_harmony` vocabulary at build time.
  Both checks and runtime use `/opt/app/tokenizer-cache`; the latter copies it into the final
  image for non-root, read-only, offline use. No model/provider calls are part of preparation.
- Pass scheduler/worker role credentials explicitly to provisioning and permission checks;
  add ephemeral CI passwords. Web still receives only its own database credentials.
- Apply product migrations before starting web in the app profile. Checks migrate their own test
  database, which does not prepare the application database used by the HTTP smoke.
- Exercise scheduler/worker SELECT/INSERT/UPDATE and denied DELETE/DDL/checks-DB access on real
  PostgreSQL. CI also tests tokenization inside the read-only runtime with networking disabled.
- Correct the outdated repository layout/setup guidance and record the audit's open findings.

## Verification

The complete local and container runs both exited successfully:

| Check | Executable evidence | Result |
|---|---|---|
| Local suite, Python 3.12 / PostgreSQL 16 | `scripts/check.py` in `.venv-app` | Ruff format/lint, mypy (81 files), Django checks, migration drift, static build; 166 application tests and 6 deployment/permission tests pass |
| Canonical Linux container suite, isolated PostgreSQL 16 | `docker compose --env-file .env.app -f compose.yaml -f compose.ci.yaml run --rm checks` | Same checks and test counts pass with only the internal backend network |
| Research and frozen eval checks, both suites | Commands invoked by [check.py](../../scripts/check.py) | 18 planning, 7 saved-run integrity and 9 selection-oracle tests pass; saved summary baseline 96/98; production selection passes all 8 applicable invariants |
| Cold runtime tokenization | Read-only, network-disabled command in [CI](../../.github/workflows/ci.yml) and [README](../../README.md) | `count_tokens('Hello world') == 2`, without a host cache mount |
| Role privileges | [test_database_roles.py](../../scripts/tests/test_database_roles.py) | Scheduler/worker SELECT/INSERT/UPDATE succeed; DELETE, DROP, TEMP creation and checks-DB access fail; administrative role flags are false; existing web boundaries pass |
| Fresh startup | `--profile app up -d --wait --wait-timeout 120`, CI override | Setup completes, all 11 product migrations apply, then web and Caddy become healthy |
| Actual HTTP/CSS | `scripts/smoke.py http://127.0.0.1:18082 --version imp01-container-correction-20260912` | Root, live, ready, env/admin/unknown 404 and static CSS checks pass |
| Image identity | [verify_image.py](../../scripts/verify_image.py), including running web | Full image ID and embedded version match |
| Existing data / repeated startup | Insert one synthetic game through the migration role, `down` without `-v`, then the same `up` | Read-only web query finds exactly one probe; no migrations to apply; HTTP/CSS smoke passes again |
| Runtime isolation | Assertions inside running web | UID 65532; no admin, migration, checks, scheduler, worker or Groq credential variables |
| Compose overrides | `config --quiet` for CI and production combinations | Both configurations resolve; production deployment itself was not exercised |
| Final documentation consistency | Planning checker and its 18 tests, `git diff --check`, UTF-8/LF and local-link validation | Pass after the final evidence/status edits |

The isolated project was `metacritic-container-correction-20260912`, with HTTP on loopback port
18082 and its own initially empty PostgreSQL volume. The normal development project and its
data were not replaced. The runtime image was `metacritic-container-correction:20260912`, with
build version `imp01-container-correction-20260912` and full image ID
`sha256:4caa7452536dd1f3a8861d24934d9712a326eff1c83680e169990ac636d2af7b`.
The checks image was `metacritic-container-correction-checks:20260912`.
These identify the tested source snapshot, not an image built from the eventual commit SHA.
Final evidence-only documentation edits followed the image build.
After verification the isolated project was stopped without deleting volumes; the normal
development PostgreSQL container remained healthy.

Local raw build/check/startup logs are retained under the ignored
`.artifacts/container-correction/` directory; they are not published CI artifacts.
The committed test and workflow commands are the reproducible verification mechanisms.
No live Metacritic or paid AI calls were made.

## Adversarial review

An adversarial self-review checked the diff against the accepted architecture, `IMP-01` exit
criteria, `NFR-06`, the risks above and the frozen eval inputs. No independent-agent review is
claimed. The concrete counterexamples and their disposition are:

- The previous checks image omitted a directory invoked by `scripts/check.py`. Both the build
  allowlist and COPY now include it; the full container run reaches its nine tests and candidate
  verifier successfully.
- The previous image attempted a vocabulary download on a cold import. The dependency stage
  now populates the hash-verified cache; runtime explicitly copies it. The network-disabled,
  read-only non-root check proves that startup does not need an online or writable cache.
- Merely mapping missing provisioning passwords would still leave a fresh application database
  without catalog tables: Django tests migrate a separate test database. This additional startup
  defect was fixed by making web depend on successful migrations; a fresh volume and the actual
  root endpoint verified the dependency chain.
- Giving web background/admin credentials to fix provisioning would violate role isolation.
  Credentials are scoped to setup/checks; actual SQL permission tests and runtime environment
  assertions cover both allowed operations and denied boundaries.
- Automatic migrations must preserve existing data on repeated startup. The isolated synthetic
  record survived container removal and recreation using the same named volume.

No unresolved material finding remains within these container corrections. The eight application
counterexamples in the audit remain open and are not covered by a green pre-existing suite.
Hosted CI for this candidate, current public VDS image/smoke/resource evidence and the clean
ingest-to-public-card revalidation remain outstanding. Accordingly, this local correction does
not mark the full `IMP-01` task or dependent tasks `Verified`, nor certify a release gate.
