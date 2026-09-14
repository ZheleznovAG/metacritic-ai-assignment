# IMP-01: hosted CI and public preview revalidation

Date: 2026-09-14 (Asia/Novosibirsk). Task `IMP-01`; requirements `DEL-01`,
`DEL-02`, `NFR-06`; risks `R-DEP-01`, `R-DEP-02`, `R-REP-01`, `R-SEC-01`,
`R-TST-01`. Current statuses belong only to [action_plan.md](../../action_plan.md).
This cycle revalidates the scaffold after the [audit corrections](implementation_corrections_batch.md).

## Source, build and execution evidence

The existing authorization recorded in [the prior correction](imp_01_correction.md#hosted-ci)
was used to push through source commit `8c766154fb147806fc67576f730b06f56aa04f03`.
The configured GitHub SSH authentication failed; the already authenticated GitHub CLI
credential helper succeeded over HTTPS to the same repository. No remote configuration
or permissions were changed.

[Hosted run 34804143596](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34804143596)
passed on that exact SHA. The workflow checks the evidence commit on its subsequent
push as well. [Execution excerpts and archive hashes](../evidence/imp-01-revalidation-2026-09-14.txt)
record the hosted result, VDS preflight, upgrade, runtime checks and external smoke.

| IMP-01 exit criterion | Executed verification and result |
|---|---|
| Clean checkout, canonical runtime, locked build | Hosted checkout/build on Ubuntu 24.04, Python 3.12.14 and PostgreSQL 16; a separate local `git archive` of the same SHA built the deployed runtime using the documented Dockerfile |
| Format/lint/types/tests/build in CI | Ruff: 112 files formatted, lint passed; mypy: 101 files; Django checks, migration drift and static build passed; 261 application tests, 6 scripts tests, 18 planning tests, 7 AI-integrity tests and 9 review-selection tests passed, together with frozen baseline/candidate verifiers |
| Runtime works with its actual restrictions | Hosted offline tokenization with network disabled and read-only filesystem passed; actual Caddy runtime and HTTP/CSS smoke passed |
| Docker/Compose access checked before deploy | VDS Engine 29.1.3, Compose 2.40.3; existing project/environment found, 76,171,939,840 bytes free; no scheduler/worker process present |
| Versioned image deployed | Clean-source runtime image `sha256:a342245359e2296c8bad6bdd69b8a8b0a6aea076aeea6ca1aa98a5cd90daa288`; image/config archive SHA-256 values matched before import; loaded image and running web identity both verified against that ID and the full source SHA |
| External endpoint and startup resources | Loopback and direct external HTTP/CSS smoke passed; Compose startup took 11.8 s; web 92.56 MiB/384 MiB, DB 32.41 MiB/512 MiB, Caddy 11.53 MiB/96 MiB at the recorded snapshot |
| Documented layout and commands | [AGENTS.md](../../AGENTS.md), [README](../../README.md), [deployment procedure](../../deploy/README.md), and the hosted workflow agree with the exercised source/build/check/migrate/verify/smoke path |

The hosted runtime image is a separate build (`sha256:9bbd17f7f80fd1d65fde4da89f0d75dec9f68b96bd814a7fef7e667f5b6d8e7d`).
The deployed archive was built from the same clean source and lock; identical image
bytes across these builds are not claimed. The deployed image's own full identity
was checked before and after transfer and against the running container.

## Upgrade and security verification

The existing `metacritic-imp01-prod` project and named PostgreSQL/Caddy volumes were
retained. Before updating the allowlisted deployment configuration, an operator-only
configuration backup and PostgreSQL custom-format dump were saved on the VDS.
`pg_restore --list` read the dump successfully. This checks archive readability;
restore capability remains a later verification task.

The documented scaffold upgrade added missing role settings. Every previously
present environment value except `APP_IMAGE`/`APP_VERSION` was compared before/after
and remained unchanged. The old image and deployment archives were retained.
`db_setup` and `migrate` both exited 0; all 16 current application migrations are
recorded. DB, web and Caddy became healthy on the existing volumes.

The VDS previously contained only the original scaffold, with no application tables
or game data. The new 20 application tables are empty. Thus this deployment proves
schema installation and volume retention, not migration or recovery of populated
review/summary data. The latter has separate deterministic migration evidence and
future operational acceptance. The local application's database was not migrated.

Read-only checks on the actual VDS confirmed:

- Web runs as `65532:65532`, with a read-only root filesystem, all capabilities
  dropped and no source bind mount; its environment excludes admin, migration,
  scheduler, worker, checks and Groq credentials.
- The actual web role has SELECT on all 21 public tables (including
  `django_migrations`), no table write privileges, privileged role flags,
  schema CREATE or database TEMP privilege. PostgreSQL has no published port.
- Caddy retains only `NET_BIND_SERVICE`. Django `check --deploy` reports exactly
  the known HTTP-preview warnings `security.W004`/`security.W008`, with none silenced.
- From the development machine without SSH forwarding: `/`, `/health/live/`,
  `/health/ready/` return 200 with the expected version/security headers;
  `/.env`, `/.env.app`, `/admin/`, `/unknown` return 404; versioned CSS is served.

## Adversarial review and limits

An adversarial self-review checked the final evidence against the `IMP-01` exit
criteria, acceptance requirements and risks above. No separate-agent/person review
is claimed. The concrete counterexamples were:

| Counterexample | Evidence or disposition |
|---|---|
| An old green run is mistaken for the corrected source | Hosted API head SHA equals `8c766154fb147806fc67576f730b06f56aa04f03`; all workflow steps succeeded |
| Dirty local files or secrets enter the deployed build | Build context came from `git archive` of that SHA; Docker uses its allowlist; config archive contains only the seven files named by the deployment procedure |
| A new tag or environment value disguises an old running image | Both archive checksums, loaded/running full image ID, embedded build version and external health payload were checked |
| Provisioning silently resets deployment settings or volumes | Existing environment values and volume names compared unchanged; backup retained; no writers running during upgrade |
| Empty database checks overstate persistence or functional acceptance | Empty pre/post state recorded explicitly; no real-data, populated-migration, ingest, summary or scheduler acceptance claimed |
| A successful HTTP preview is mistaken for release readiness | TLS/DNS, reboot/restore, hourly windows, capacity and final `AC-DEL-01/02` remain later gate criteria |
| A green source run does not check the evidence changes | The focused evidence commit is pushed through the same deterministic workflow; its result must be checked before ending this cycle |

The tracker update passed `python -B research/planning/check_plan.py` and all 18
planning negative controls. `git diff --check` passed; the four changed files were
checked against the local SSH host/key and password/secret values without publishing
those values. No runtime, workflow or dependency-lock file changed in this cycle.

No unresolved material finding remains in the scaffold revalidation. The independent
hosted execution and direct public runtime checks supply the missing technical
evidence for `IMP-01`; [the tracker](../../action_plan.md) records its disposition.
`IMP-02–05` still need their own current functional/public evidence. The empty public
catalog makes the next `IMP-02` source-to-card revalidation necessary. No live
Metacritic/provider calls were made, and no subsequent task or gate was executed.
