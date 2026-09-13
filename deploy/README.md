# IMP-01 early deployment

This procedure deploys the read-only catalog preview and its schema. It does not certify G6 or install permanent scheduler/worker services. Docker/Compose and deploy-user daemon access must already work. Use the `DEPLOY_SSH_*` values from the ignored operator `.env`; never transfer that file or print it.

## Build and first installation

1. Complete the README checks. Choose a unique build version from a source commit or a frozen source snapshot. Build with that version before assigning its tag:

```sh
docker build --target runtime --build-arg APP_VERSION=<build-version> -t metacritic-imp01:<build-version> .
docker image inspect metacritic-imp01:<build-version> --format '{{.Id}}'
```

Record the full `sha256:...` image ID, build version and source identity. The build version is embedded in a read-only file and OCI label; it is not derived from the resulting image ID and cannot be changed by runtime `APP_VERSION`.

2. Export with `docker save --output <image-archive> metacritic-imp01:<build-version>`. Create a separate configuration archive containing only `compose.yaml`, `compose.production.yaml`, `deploy/Caddyfile`, `.env.app.example`, `scripts/init_env.py`, `scripts/verify_image.py` and `scripts/smoke.py`. Record both archive SHA-256 values.
3. Verify port 18081 and the new `metacritic-ai-assignment-imp01` directory are unused. Through the already trusted SSH connection, create the directory with `umask 077` and transfer the two archives. Preserve SSH host-key verification and existing directories.
4. Verify both archive checksums on VDS before extraction/import. Extract configuration, then run `docker load -i <image-archive>`.
5. Generate the application/DB environment and verify image identity before startup:

```sh
python3 scripts/init_env.py --production --host <public-host> --version <build-version>
python3 scripts/verify_image.py --image metacritic-imp01:<build-version> --image-id sha256:<recorded-full-image-id> --version <build-version>
docker compose -p metacritic-imp01-prod --env-file .env.app -f compose.yaml -f compose.production.yaml config --quiet
docker compose -p metacritic-imp01-prod --env-file .env.app -f compose.yaml -f compose.production.yaml --profile app up -d --wait --wait-timeout 120
python3 scripts/verify_image.py --image metacritic-imp01:<build-version> --image-id sha256:<recorded-full-image-id> --version <build-version> --container metacritic-imp01-prod-web-1
python3 scripts/smoke.py http://127.0.0.1:18081 --version <build-version>
```

The app profile enforces `db_setup -> migrate -> web -> caddy`: web starts only after migrations complete successfully. Provisioning creates restricted web/scheduler/worker roles and grants current/future table SELECT to web; the production setup creates no checks database or checks role. Administrative and role-provisioning credentials stay in the one-shot setup service; web receives only its own login and migrate receives the schema owner's login. The existing migrations preserve table data. To run migrations explicitly, use `--profile app run --rm migrate` with the same project/configuration; enabling the app profile also makes `db_setup` available.

6. Repeat the HTTP/CSS smoke from a separate machine against the public host without an SSH tunnel. Record the source identity, full image ID, build version, checksums, status and resources. Never publish full Compose/inspect output containing environment values.

Only Caddy publishes a port. PostgreSQL uses the internal network and named volume. Web runs as UID/GID 65532, with a read-only filesystem and no source bind mount. The official Caddy binary requires `NET_BIND_SERVICE` in its capability bounding set; other capabilities remain dropped.

## Upgrade of the original IMP-01 preview

Keep the existing project name, `.env.app` and named volumes. First prepare and verify the new image/configuration archives as above. After replacing the known configuration files:

```sh
python3 scripts/init_env.py --upgrade-scaffold
```

This explicit, repeatable upgrade appends missing WEB/MIGRATE/CHECKS/SCHEDULER/WORKER role settings. It preserves existing credentials and deployment settings, including `POSTGRES_PASSWORD`; do not rerun fresh initialization or delete a volume. Update only `APP_IMAGE`/`APP_VERSION` to the new release, verify the loaded image, then use the same up/image-verification/smoke commands above. The app profile runs migrations before web starts.

Provisioning handles the empty original scaffold and its optional `django_migrations` table, transferring that table to the migration owner without deleting rows. Unknown tables owned by the old administrator cause a refusal before ownership changes; product data requires a separately reviewed migration. Repeated provisioning preserves existing tables and removes excess direct web grants. The upgrade does not remove the administrative role.

## Restart, redeploy and rollback

Use the same Compose project, configuration and volumes. A later release needs verified archives, a deliberately updated image reference, migrate/up, image verification and external smoke. Keep a previously verified compatible image available. Rolling back to the original pre-correction image/configuration would restore the old credential contract and needs a separate decision; changing a displayed version is not rollback verification.

To stop while retaining state, use the same Compose command with `--profile app down`. Never add `-v`, prune volumes, alter another project or remove the whole deploy home. Preserve the image/configuration archives used for verification and recovery. Firewall/SSH/system package changes are outside this procedure.

TLS, DNS/80/443, host reboot, application hourly windows, backup/restore and production capacity remain later gate checks. GitHub CI never deploys. An unfinished candidate/correction may be committed locally with its actual status; repository publication still requires the owner's selected remote and authorization. Hosted run URL and tested SHA are recorded after the run, and CI also checks the evidence commit.
