# PUB-01: supervised scheduler/worker services

Task `PUB-01`. Requirements/risks per `implementation_plan.md#pub-01`:
verified image/commit deployed with persistent named volumes, supervision,
scoped secrets and a UTC scheduler; DNS/TLS/ingress and resource startup
verified on the VDS; hostname/ports/access never guessed. Current
task/gate status belongs only to [action_plan.md](../../action_plan.md).

## Scope of this cycle

The `f0e89a4` audit's finding `A01` was concrete and unaddressed:
`compose.yaml` had no `scheduler`/`worker` services at all, so every real
AI summary and scheduled discovery run to date (`IMP-03/04/07`) came from
an operator manually SSHing in and running `scripts/run_scheduler.py`/
`run_worker.py` by hand. This cycle closes that specific gap: permanently
supervised `scheduler` and `worker` Compose services, so the deployed site
processes hourly and generates summaries without an operator present.

## Design decision: worker secrets

The `worker` service needs `GROQ_API_KEY` to run unattended, but
`.env.app.example` states an existing, deliberate rule: "Keep SSH/Groq
keys in `.env`, never in this file" -- and `.env.app` is the only file
already transferred to and read from on the deploy host. Putting the
Groq key there would break that boundary; keeping the worker fully manual
would defeat the point of supervision. Asked the owner directly rather
than assuming: the answer was a new, minimal, untracked `.env.worker` file
(mode 0600) carrying only `GROQ_API_KEY`/`GROQ_API_BASE_URL`/
`GROQ_API_TIMEOUT_SECONDS`, loaded via Compose's own `env_file:` on the
`worker` service alone -- distinct from both `.env.app` (unaffected) and
the operator's local `.env` (never transferred to the deploy host, still
true; `.env.worker` is a different file that never carries
`DEPLOY_SSH_*` values).

## Fix

- `compose.yaml`: new `scheduler` (`python app/manage.py run_scheduler`,
  continuous loop) and `worker` (`python app/manage.py run_worker`,
  continuous loop) services, `profiles: [app]`, each under its own
  already-provisioned restricted role (`SCHEDULER_DB_USER`/
  `WORKER_DB_USER` -- these roles existed since `IMP-03`/`IMP-04`'s own
  provisioning, just never consumed by a supervised service), `restart:
  unless-stopped`, `depends_on: migrate: service_completed_successfully`.
  Both join `backend` (internal, DB access) and `edge` (the one
  non-internal network in this file, for real outbound HTTP to Metacritic
  and Groq) -- `web` deliberately stays `backend`-only since it never
  makes outbound calls. A shared `x-background-service` anchor (mirroring
  the file's existing `*logging`/`*app-environment` convention) factors
  out the hardening profile both services share.
- `.env.worker.example` (new, tracked template) and a `.gitignore`
  exception for it, matching `.env.app.example`'s pattern.
- `deploy/README.md`: documents creating `.env.worker` as a required step
  in both the first-install and upgrade procedures (see Adversarial
  review), and that the app profile now starts `{web, scheduler, worker}`
  together after migrations, not just `web`.
- `README.md`: the "Deployment boundary" section's forward-looking note
  ("scheduler/worker... remain part of `PUB-01`") is updated now that this
  cycle delivers them.

## Local verification

Built the runtime image locally and brought up the full `app` profile
stack (`docker compose --env-file .env.app -p metacritic-imp01 --profile
app up -d --wait`) twice -- once before, once after the DRY refactor --
both times all six containers (`db`, `web`, `scheduler`, `worker`,
`caddy`, plus the one-shot `db_setup`/`migrate`) reached `Healthy`/`Exited
(0)` within the wait timeout. `docker compose ... --profile app config`
confirms the `x-background-service` anchor resolves identically on both
services (`cap_drop`, `security_opt`, `mem_limit`, `logging`,
`healthcheck: disable`, `restart`, `networks` all present).

With an empty `.env.worker` (`GROQ_API_KEY=`, matching how a fresh deploy
starts before the operator sets a real key), the `worker` container made
**real HTTP calls to `backend.metacritic.com`** and correctly completed
several genuine review-collection jobs (`review_job_id=17 ... state=complete
page=3 fetched=30`, three more with real fetched counts) -- proving the
review-collection half runs unattended with no Groq configuration at all,
exactly as `run_worker.py`'s own graceful-degradation design intends. No
Groq call was attempted (correctly; the key was empty). The `scheduler`
container found an already-`succeeded` run for the current hour from
earlier local testing and correctly reported `skipped_duplicate` rather
than re-processing -- real idempotency, not simulated. The stack was
torn down (`--profile app down`, no `-v`) once this was confirmed, rather
than left running an unattended loop against the real site with no
further evidence to gain from it.

## Adversarial review

An independent `/code-review high` pass found three items, all fixed:

- **Fixed:** the Upgrade section of `deploy/README.md` never mentioned
  `.env.worker` at all -- an operator upgrading an existing pre-`PUB-01`
  deployment via `init_env.py --upgrade-scaffold` (which only touches
  `.env.app`) would get a `worker` container that starts fine but silently
  never generates summaries, with no error or health-check failure to
  surface the gap. Added an explicit paragraph to that section.
- **Fixed:** the first-install section's `.env.worker` instruction was
  placed *after* the fenced code block that already runs `up`, so a
  reader following the steps in order would start the stack before the
  prerequisite file existed. Moved the file-creation step into the code
  block itself, before `up`.
- **Fixed:** `scheduler` and `worker` duplicated their entire hardening
  profile (`read_only`, `cap_drop`, `security_opt`, `mem_limit`,
  `logging`, `healthcheck: disable`) verbatim, unlike the file's own
  established anchor convention for shared settings -- a future change to
  one would silently miss the other. Factored into the new
  `x-background-service` anchor.

## Verification

`docker compose config --quiet` passes for both `compose.yaml` alone and
`compose.yaml` + `compose.production.yaml` together (with a placeholder
`APP_IMAGE`, as the production overlay requires one explicitly). The full
`scripts/check.py` suite (339 application tests, ruff format/lint, strict
mypy, migration drift, static build, all offline evals/verifiers) passes
unchanged -- this cycle touches no Python source.

## Live VDS deployment

Owner unblocked VDS SSH access mid-cycle. Deployed source `1fc3fda`
(this cycle's own commit) as an upgrade of the running `37b44fb`
preview, following `deploy/README.md`'s upgrade procedure with a
`deploy_release.py` script matching the pattern of every prior live
deployment (`IMP-02/05/07`, `SIM-VER-01`):

- Pre-flight: confirmed no leftover manual `run_scheduler.py`/
  `run_worker.py` processes, confirmed the running `web` image matched
  the audit's recorded `sha256:1a066e...`, snapshotted every table's row
  count and both named-volume sets before touching anything.
- Backup: `configuration.tar.gz` + a real `pg_dump -Fc` (verified
  readable via `pg_restore --list` before proceeding), saved to
  `backups/before-1fc3fda-<timestamp>/`, joining the existing backup
  history from every prior release.
- Build/transfer: built `metacritic-imp01:1fc3fda...` locally
  (`sha256:5413391...`), exported and SHA-256-verified both the image and
  configuration archives after SCP transfer, before extraction/import.
- `.env.worker` created directly on the VDS (mode 600) from the
  operator's local Groq credential, via a piped SSH command whose content
  was never printed to any log or terminal output; confirmed present
  with the right permissions without ever reading its contents back.
- **Found and fixed one real deploy-tooling bug during this run:**
  `docker compose ... up -d --wait --wait-timeout 180` aborted with
  `container ... has no healthcheck configured` for `worker` -- the VDS
  runs Compose 2.40.3 (local dev uses v5.4.0), and that older version
  refuses to `--wait` on a container with an explicitly disabled
  healthcheck at all, unlike the newer one. The containers themselves had
  already started correctly; only the wrapper script's `check=True` on
  that one command halted before reaching the verification steps. Diagnosed
  via `docker compose ps` showing every container `running`/`Exited (0)`
  as expected, then completed the remaining steps manually. Fixed
  `deploy/README.md`'s own documented command to drop `--wait` for this
  profile and check `scheduler`/`worker` separately via `ps`, so the next
  deploy doesn't hit the same wall.
- Post-deploy verification, all passing: `verify_image.py --container
  metacritic-imp01-prod-web-1` (image identity), `smoke.py` (9/9 checks:
  `/`, both health endpoints, `.env`/`.env.app`/`/admin/`/unknown paths
  all 404, static CSS served), every pre-existing table's row count
  preserved (`catalog_game` 39, `reviews_review` 12409, etc. -- all present
  and non-decreasing), both named-volume sets unchanged, and a genuinely
  external HTTP request (not an SSH tunnel) to the public port returning
  `200` for `/` and `/health/live/`.
- **Real autonomous activity within minutes of startup, with zero operator
  intervention:** the scheduler's own log shows `run_id=4
  trigger_key=scheduled:2026-09-15T19:00:00Z outcome=succeeded
  selected=20 processed=20 failed=0` for the live 19:00 UTC hour slot,
  followed by correct `skipped_duplicate` on subsequent ticks within the
  same hour (real idempotency, not simulated). The worker's log shows real
  review-collection jobs against newly-discovered games (`review_job_id=122
  ... state=complete page=1 fetched=1`, several correctly-terminal
  `state=empty` routes) and correctly honest `insufficient_data` summary
  states for games with too few reviews -- no fabrication, no crash. Table
  counts grew during the run itself (`catalog_game` 39 -> 59,
  `summaries_summaryjob` 2 -> 9, `summaries_reviewsummary` 2 -> 8) with
  zero new `summaries_summaryattempt` rows, meaning zero new Groq calls
  were spent in this verification window -- the newly-discovered games'
  sparse review counts were correctly and cheaply resolved as
  `insufficient_data` without ever needing a provider call.
- Left running, supervised, in production: this is the first time in the
  project's history that scheduler and worker keep processing without an
  operator SSHing in for each tick.

This closes `PUB-01`'s scheduler/worker supervision and versioned-deploy
scope. Not in this cycle's scope, deferred to `PUB-02`/`PUB-03` as
`implementation_plan.md` already specifies: TLS/DNS (still the accepted
HTTP-only preview), host reboot persistence, two consecutive full
application-hour windows as sustained evidence (one is shown above), and
external unauthorized-user smoke.
