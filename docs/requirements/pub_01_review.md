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

This closed `PUB-01`'s scheduler/worker supervision and versioned-deploy
scope at the time. `implementation_plan.md#pub-01`'s own text also
requires "Проверены DNS/TLS/ingress" -- that half was still genuinely
open here (no domain existed yet to get a certificate for), not correctly
deferrable to `PUB-02`/`PUB-03` as first written. See "TLS/DNS" below for
its closure, once a hostname became available, within this same task.
Host reboot persistence, two consecutive full application-hour windows,
and external unauthorized-user smoke are `PUB-02`/`PUB-03`'s own scope
(`docs/requirements/pub_02_review.md`, `pub_03_review.md`).

## TLS/DNS (follow-up within this task)

`PUB-01`'s own acceptance requires DNS/TLS verified, not just the
scheduler/worker supervision above -- deferring it to `PUB-02`/`PUB-03`
in this doc's first version was a misattribution, corrected once the
owner explicitly asked for it to be resolved "in the task where it should
have been decided" and provided the hoster-provided reverse-DNS hostname
`v978670.hosted-by-vdsina.com` (confirmed via `nslookup` to resolve to
this VDS's own public IP, `<production-ip>`, before any of this was used).

- `deploy/Caddyfile.production` (new, tracked): a real-domain site block
  with Caddy's default `auto_https` (no more `auto_https off`), obtaining
  and renewing a real Let's Encrypt certificate; the prior `:8080` block
  is kept, container-internal only, for the image's own `HEALTHCHECK`
  path and the `caddy` service's own healthcheck (both hit
  redirect-exempt health endpoints, so unaffected by any of this).
  Validated with `caddy validate`/`caddy fmt` locally before ever
  touching the VDS.
- `compose.production.yaml`: `caddy` mounts `deploy/${CADDYFILE_NAME:-Caddyfile}`
  (defaults to the plain-HTTP preview; this deployment's own `.env.app`
  sets `CADDYFILE_NAME=Caddyfile.production` -- see Adversarial review)
  and publishes `80`/`443` on `0.0.0.0` (for the ACME HTTP-01 challenge
  and real HTTPS traffic) alongside the existing `18081` on
  `${APP_HTTP_BIND:-127.0.0.1}` (still available for on-host diagnostics).
- VDS `.env.app`: `DJANGO_ALLOWED_HOSTS` gained the new hostname
  (appended, the existing IP/`localhost` entries untouched) and
  `DJANGO_HTTPS` flipped to `true`, enabling Django's own
  `SECURE_SSL_REDIRECT`/HSTS now that trusted TLS actually exists in
  front of it.
- Deployed with the same care as the original upgrade: config backed up
  first (`backups/before-tls-20260916/`), config validated
  (`docker compose config --quiet`) before `up -d` (no `--wait`, same
  Compose-version reason as the original deploy).
- **Verified working, live:** Caddy's own log shows the full real ACME
  sequence -- account registration, HTTP-01 challenge served to (and
  validated by) Let's Encrypt's real validation servers, `"certificate
  obtained successfully"`. `curl https://v978670.hosted-by-vdsina.com/`
  returns `200` with a certificate `curl` accepts with no `-k` flag --
  proof by itself that this is a genuinely trusted certificate, not
  self-signed. `curl http://.../` redirects `308` to the same URL over
  HTTPS. The full `scripts/smoke.py` (8/8 checks) passed against the
  HTTPS URL, run both from the VDS itself and from a separate external
  machine.
- **Found one real, expected side effect, not a regression (with one
  factual correction from adversarial review -- see below):**
  `DJANGO_HTTPS=true` is a single setting applied to every request
  regardless of which Caddy block routed it. The old loopback `18081`
  path (still `:8080` internally, still sending `X-Forwarded-Proto:
  http`) now `30x`-redirects every *non-exempt* path once trusted TLS
  exists elsewhere, since Django correctly treats that path as insecure;
  the redirect-exempt health endpoints (and therefore every container
  healthcheck and `verify_image.py --container`) are unaffected.

## Adversarial review

An independent `/code-review high` pass on the uncommitted diff found six
items, all fixed:

- **Fixed (functional):** `compose.production.yaml` unconditionally
  mounted `Caddyfile.production` (hardcoded to this one hostname),
  silently breaking `deploy/README.md`'s own documented "fresh HTTP-only
  preview for a new host" flow -- a deploy for any other host would try
  (and fail) to obtain a certificate for the wrong domain instead of
  serving plain HTTP. Fixed by mounting `deploy/${CADDYFILE_NAME:-Caddyfile}`
  (defaulting to the original plain-HTTP file) and setting
  `CADDYFILE_NAME=Caddyfile.production` only in this deployment's own
  `.env.app`, matching how `APP_IMAGE`/`APP_VERSION` are already
  per-environment. `.env.app.example` documents the new variable.
- **Fixed (factual error in this doc and `deploy/Caddyfile.production`'s
  own comment):** the claim that the old loopback path's redirect goes
  "to the real HTTPS hostname" was wrong -- verified directly against the
  live VDS (`curl -v http://127.0.0.1:18081/` before this fix), Django's
  `SECURE_SSL_REDIRECT` builds the target from the *request's own* `Host`
  header (`https://127.0.0.1:18081/`, since `DJANGO_ALLOWED_HOSTS` keeps
  the IP/`localhost` entries), not a fixed hostname -- and nothing serves
  HTTPS there, so it is a dead end, not a working hop. Corrected here, in
  `deploy/Caddyfile.production`'s comment, and in
  `deploy/README.md`, which now says explicitly to target the real
  hostname directly for any future smoke, never this port, once
  `DJANGO_HTTPS=true`.
- **Fixed (documentation staleness):** `README.md` still claimed, a few
  lines from text this same diff had just updated, that "trusted
  TLS/hostname remain mandatory before G6" (describing the *local/CI*
  container preview, which is correctly always plain HTTP and unaffected
  by any of this -- the wording just didn't make that scope clear) and
  that "TLS, DNS... remain PUB-02/PUB-03" (wrong task attribution, and now
  also just wrong -- it is done). Both corrected.
- **Fixed (reuse):** the container-internal `:8080` block was duplicated
  near-verbatim between `deploy/Caddyfile` and `deploy/Caddyfile.production`.
  Extracted into a shared `deploy/Caddyfile.snippets` (a Caddy named
  snippet), `import`-ed by both files; mounted alongside each Caddyfile in
  both `compose.yaml` and `compose.production.yaml` (missing the mount in
  the local/CI `compose.yaml` would have broken every local/CI Caddy
  startup, since `deploy/Caddyfile` now imports it too -- caught and fixed
  before commit by actually starting the local stack, not just validating
  syntax).
- **Fixed (silent behavior change):** the `18081` bind address was
  hardcoded to `127.0.0.1`, dropping the `${APP_HTTP_BIND}` interpolation
  `.env.app.example` still documents for this exact port. Restored.
- **Fixed (CI gap):** CI validated `compose.production.yaml`'s YAML
  syntax but never parsed either actual Caddyfile it references. Added a
  `caddy validate` step for both `deploy/Caddyfile` and
  `deploy/Caddyfile.production` (with the shared snippet mounted) to
  `.github/workflows/ci.yml`.

All fixes verified: both Caddyfiles pass `caddy validate`/`caddy fmt`
with the shared snippet; the local dev stack was actually started (not
just config-validated) to confirm `deploy/Caddyfile`'s new `import` line
does not break the far more commonly exercised local/CI path; the
corrected configuration was redeployed to the live VDS (`CADDYFILE_NAME=
Caddyfile.production` set explicitly in its `.env.app` so the redeploy
does not silently revert it to plain HTTP), and `https://v978670.hosted-by-vdsina.com/`
still returns `200` with the same, already-cached Let's Encrypt
certificate (no new ACME request needed -- confirmed from the caddy
container's own log, which shows certificate management resuming rather
than a fresh `"obtaining certificate"` sequence) after the redeploy. The
full `scripts/check.py` suite (339 tests, ruff, mypy, migrations, offline
evals) passes unchanged; no application code was touched by this cycle.

This closes `PUB-01`'s DNS/TLS/ingress requirement in full; combined with
the scheduler/worker supervision above, `PUB-01` is genuinely complete
against its own stated acceptance criteria, not partially deferred.
