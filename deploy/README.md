# IMP-01 early deployment

This procedure deploys the catalog preview and schema, and (since `PUB-01`) the supervised `scheduler`/`worker` services that keep it processing without an operator SSHing in for each tick. It does not certify G6. Docker/Compose and deploy-user daemon access must already work. Use the `DEPLOY_SSH_*` values from the ignored operator `.env`; never transfer that file or print it -- `.env.worker` (below) is a distinct file, safe to keep on the deploy host, and never carries `DEPLOY_SSH_*` values.

## Build and first installation

1. Complete the README checks. Choose a unique build version from a source commit or a frozen source snapshot. Build with that version before assigning its tag:

```sh
docker build --target runtime --build-arg APP_VERSION=<build-version> -t metacritic-imp01:<build-version> .
docker image inspect metacritic-imp01:<build-version> --format '{{.Id}}'
```

Record the full `sha256:...` image ID, build version and source identity. The build version is embedded in a read-only file and OCI label; it is not derived from the resulting image ID and cannot be changed by runtime `APP_VERSION`.

2. Export with `docker save --output <image-archive> metacritic-imp01:<build-version>`. Create a separate configuration archive containing only `compose.yaml`, `compose.production.yaml`, `deploy/Caddyfile`, `deploy/Caddyfile.production`, `.env.app.example`, `.env.worker.example`, `scripts/init_env.py`, `scripts/verify_image.py`, `scripts/smoke.py` and `scripts/grant_manual_run_access.py`. Record both archive SHA-256 values.
3. Verify port 18081 and the new `metacritic-ai-assignment-imp01` directory are unused. Through the already trusted SSH connection, create the directory with `umask 077` and transfer the two archives. Preserve SSH host-key verification and existing directories.
4. Verify both archive checksums on VDS before extraction/import. Extract configuration, then run `docker load -i <image-archive>`.
5. Generate the application/DB environment, create the worker's Groq secrets file, and verify image identity before startup:

```sh
python3 scripts/init_env.py --production --host <public-host> --version <build-version>
cp .env.worker.example .env.worker && chmod 0600 .env.worker  # then set its real GROQ_API_KEY
python3 scripts/verify_image.py --image metacritic-imp01:<build-version> --image-id sha256:<recorded-full-image-id> --version <build-version>
docker compose -p metacritic-imp01-prod --env-file .env.app -f compose.yaml -f compose.production.yaml config --quiet
docker compose -p metacritic-imp01-prod --env-file .env.app -f compose.yaml -f compose.production.yaml --profile app up -d
python3 scripts/verify_image.py --image metacritic-imp01:<build-version> --image-id sha256:<recorded-full-image-id> --version <build-version> --container metacritic-imp01-prod-web-1
python3 scripts/smoke.py http://127.0.0.1:18081 --version <build-version>
```

`compose ... up` above also runs the one-shot `db_grants` service (BON-22) automatically, between
`migrate` and `web`: it names the exact narrow write grants web needs for its own sessions, the
manual-run command row, the admission rate-limit lock and login-throttle audit rows, and one
column of `auth_user` -- tables `provision_db.py` cannot yet name (it runs before `migrate`).
`docker compose -p metacritic-imp01-prod ps db_grants` should show `Exited (0)`. Create the first
operator account once web is up (never prints the password to any log docs read):

```sh
docker compose -p metacritic-imp01-prod --env-file .env.app -f compose.yaml -f compose.production.yaml run --rm migrate python app/manage.py create_operator <username>
```

Do not add `--wait` to that `up`: `scheduler`/`worker` disable their inherited HTTP healthcheck (it doesn't apply to a non-HTTP process), and Docker Compose 2.40 (confirmed on the VDS during `PUB-01`'s first upgrade; Compose v5 locally does not have this problem) refuses to `--wait` on a container with a disabled healthcheck at all ("has no healthcheck configured"), aborting before ever reaching the verification steps below even though the containers themselves start correctly. `verify_image.py`'s own `--container` check already waits out `web`'s real healthcheck; confirm `scheduler`/`worker` separately with `docker compose -p metacritic-imp01-prod ps` (expect `running`, no health column since none is configured) before moving on.

`.env.worker` is the *only* file the `worker` service reads Groq credentials from; `.env.app` never carries them, same discipline as the operator's own `.env`. `worker` starts and runs review-collection work even without this file (its own `env_file:` entry is optional) -- summary generation stays idle ("GROQ_API_KEY not set") until it exists, so a missed step here degrades a feature silently rather than failing startup; treat it as a required step, not an optional one.

The app profile enforces `db_setup -> migrate -> db_grants -> web -> {scheduler, worker} -> caddy`: all three application processes start only after migrations (and, for web, the BON-22 write-allowlist) complete successfully, each under its own restricted role, and restart automatically (`unless-stopped`) if they exit. `scheduler`/`worker` depend only on `migrate` (their own broad default-privilege grants already cover every table, including the new ones, with no extra step); only `web` needs `db_grants` first. Provisioning creates restricted web/scheduler/worker roles and grants current/future table SELECT to web; the production setup creates no checks database or checks role. Administrative and role-provisioning credentials stay in the one-shot setup service; web/scheduler/worker each receive only their own login. The existing migrations preserve table data. To run migrations explicitly, use `--profile app run --rm migrate` with the same project/configuration; enabling the app profile also makes `db_setup` available.

6. Repeat the HTTP/CSS smoke from a separate machine against the public host without an SSH tunnel. Record the source identity, full image ID, build version, checksums, status and resources. Never publish full Compose/inspect output containing environment values.

Only Caddy publishes a port. PostgreSQL uses the internal network and named volume. Web runs as UID/GID 65532, with a read-only filesystem and no source bind mount. The official Caddy binary requires `NET_BIND_SERVICE` in its capability bounding set; other capabilities remain dropped.

## Enabling trusted TLS once a hostname is available

The initial `compose.production.yaml` above uses `deploy/Caddyfile`, plain HTTP only on `127.0.0.1:<port>:8080` -- correct before any real hostname exists, since Let's Encrypt needs a domain that already resolves to this host. Once one does (a hoster-provided reverse-DNS hostname is enough; verify with `nslookup <hostname>` before proceeding, and confirm it resolves to this VDS's own public IP):

`deploy/Caddyfile.production` already names this project's one real deployed
hostname (`v978670.hosted-by-vdsina.com`, the hoster-provided reverse-DNS
name -- verified with `nslookup` to resolve to this VDS's own public IP
before it was ever used here); a genuinely different future hostname would
need this file's site address changed accordingly (`caddy fmt --overwrite`
afterward) and re-verified the same way. To turn it on:

1. `compose.production.yaml`'s `caddy` service already publishes `80`/`443` on `0.0.0.0` and mounts `deploy/Caddyfile.production` -- no further edits needed there.
2. Add the hostname to `.env.app`'s `DJANGO_ALLOWED_HOSTS` (append, do not replace the existing IP/`localhost` entries) and set `DJANGO_HTTPS=true`.
3. `docker compose ... --profile app up -d` (again, no `--wait`, same reason as above) recreates `web` (new environment) and `caddy` (new config/ports/volumes). Confirm from `docker logs <project>-caddy-1` that it reaches `"certificate obtained successfully"` for the hostname -- this needs port `80` reachable from the internet for the ACME HTTP-01 challenge; a host firewall blocking it would show a timed-out or connection-refused challenge attempt instead.
4. Verify: `curl https://<hostname>/` returns `200` with a certificate `curl` accepts by default (no `-k` needed -- that alone proves a real, trusted cert, not a self-signed one); `curl http://<hostname>/` redirects (`308`) to the same URL over HTTPS; `python3 scripts/smoke.py https://<hostname> --version <build-version>` passes all checks, run both from the VDS itself and from a separate external machine.

**Once `DJANGO_HTTPS=true`, the old loopback smoke command above
(`scripts/smoke.py http://127.0.0.1:18081 ...`) stops returning plain
`200`/`404` for non-health paths** -- `/`, `/admin/`, etc. now `30x`-redirect
to the real HTTPS hostname, same as any other insecure request Django's own
`SECURE_SSL_REDIRECT` sees (`/health/live/`/`/health/ready/` stay exempt, so
container healthchecks and `verify_image.py --container` are unaffected).
This is expected once trusted TLS is live, not a regression; re-point any
future on-host smoke at the real HTTPS hostname instead (works identically
from the VDS itself, since DNS already resolves there).

## Upgrade of the original IMP-01 preview

Keep the existing project name, `.env.app` and named volumes. First prepare and verify the new image/configuration archives as above. After replacing the known configuration files:

```sh
python3 scripts/init_env.py --upgrade-scaffold
```

This explicit, repeatable upgrade appends missing WEB/MIGRATE/CHECKS/SCHEDULER/WORKER role settings. It preserves existing credentials and deployment settings, including `POSTGRES_PASSWORD`; do not rerun fresh initialization or delete a volume. Update only `APP_IMAGE`/`APP_VERSION` to the new release, verify the loaded image, then use the same up/image-verification/smoke commands above. The app profile runs migrations before web starts.

Upgrading a pre-`PUB-01` deployment: `init_env.py --upgrade-scaffold` does not create `.env.worker` (it only touches `.env.app`). If it is not already present next to `compose.yaml` from an earlier run of this procedure, copy `.env.worker.example` to `.env.worker`, `chmod 0600` it and set its real `GROQ_API_KEY` before `up` -- otherwise `worker` starts but silently never generates summaries ("GROQ_API_KEY not set"), with no error or health-check failure to surface the gap. Already having `.env.worker` from a prior upgrade needs no action.

Provisioning handles the empty original scaffold and its optional `django_migrations` table, transferring that table to the migration owner without deleting rows. Unknown tables owned by the old administrator cause a refusal before ownership changes; product data requires a separately reviewed migration. Repeated provisioning preserves existing tables and removes excess direct web grants. The upgrade does not remove the administrative role.

## Restart, redeploy and rollback

For the `BON-21` upgrade, first preserve a database/configuration backup and the
previous image reference. Wait for an idle core lease, then stop only this
project's scheduler/worker before applying the additive `processing.0003`
migration. Keep web/DB/ingress available during preparation; run the normal
migrate/up and image identity checks. Verify `/ops/`, `/ops/status/`, real
scheduler/worker heartbeat and the existing catalog through public HTTPS.
Never seed production runs or counters to make the monitoring demonstration pass.

To disable the feature, set `OPS_MONITORING_ENABLED=false` in the existing
`.env.app` and recreate web/scheduler/worker: both monitoring endpoints return
404 and background work continues. Re-enabling needs no data migration. For an
application rollback, stop background processes, restore the prior image/config
references and recreate them while retaining the additive schema and volumes.
Do not reverse the migration or delete batch/history rows during rollback. The
pre-Bonus image ignores the new tables/column; preserve the same role grants.
An interrupted pre-upgrade run without frozen membership is reported honestly
as `legacy_batch_unavailable`, with its remaining candidates retried by a later run.

Use the same Compose project, configuration and volumes. A later release needs verified archives, a deliberately updated image reference, migrate/up, image verification and external smoke. Keep a previously verified compatible image available. Rolling back to the original pre-correction image/configuration would restore the old credential contract and needs a separate decision; changing a displayed version is not rollback verification.

To stop while retaining state, use the same Compose command with `--profile app down`. Never add `-v`, prune volumes, alter another project or remove the whole deploy home. Preserve the image/configuration archives used for verification and recovery. Firewall/SSH/system package changes are outside this procedure.

Host reboot, application hourly windows, backup/restore and production capacity are `PUB-02` scope, recorded there once performed rather than duplicated here. TLS/DNS/80/443 are covered above (`PUB-01`); an *unauthorized* external smoke pass over the resulting HTTPS URL, run from outside this host, is `PUB-03`. GitHub CI never deploys. An unfinished candidate/correction may be committed locally with its actual status; repository publication still requires the owner's selected remote and authorization. Hosted run URL and tested SHA are recorded after the run, and CI also checks the evidence commit.
