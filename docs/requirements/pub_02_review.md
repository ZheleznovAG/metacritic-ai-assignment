# PUB-02: real hourly operation and state persistence

Task `PUB-02`. Requirements/risks per `implementation_plan.md#pub-02`:
two consecutive real application hourly windows with genuine processing
results; persistent state survives restart/redeploy and a controlled host
reboot; a backup restores into isolated storage without overwriting the
working database; storage forecast and AI arrivals/cache/completions/
backlog/oldest age measured on real data. Current task/gate status
belongs only to [action_plan.md](../../action_plan.md).

## Restart persistence

`docker compose -p metacritic-imp01-prod restart` (all five `app`-profile
containers plus the one-shot `db_setup`/`migrate`) was run against the
live deployment. All containers came back `running`/`Exited (0)` and
`web`/`db`/`caddy` reported `healthy` within 22 seconds; a local smoke
request (`curl http://127.0.0.1:18081/`) returned `200` immediately after.

## Host reboot persistence

A real `sudo reboot` was issued on the VDS by the owner (interactive sudo
password required; this session has no TTY to supply one, so the owner
ran it directly -- consistent with the same access boundary already
recorded for `git push` elsewhere in this cycle). Verified:

- Host `uptime` reset to a value matching real elapsed wall-clock time
  since the reboot command (confirmed against the reboot broadcast's own
  timestamp), not a continuation of pre-reboot uptime -- ruling out a
  false positive from checking too early.
- All five `app`-profile containers (`caddy`, `db`, `scheduler`, `web`,
  `worker`) came back automatically, with **no operator command run after
  the reboot** -- Docker's own boot-time autostart plus each service's
  `restart: unless-stopped` policy is what brought them back, exactly the
  supervision `PUB-01` added.
- Every table's row count was preserved and had *grown* further since the
  pre-reboot snapshot (`reviews_review` 12409 -> 12539,
  `summaries_summaryattempt` 2 -> 11, etc.) -- scheduler/worker resumed
  real autonomous processing immediately after boot, not just the static
  web preview.
- Local smoke (`curl http://127.0.0.1:18081/`) returned `200` post-reboot,
  and a genuinely external HTTP request from a separate machine (not an
  SSH tunnel) to both `/` and `/health/ready/` also returned `200`.

## Isolated restore

Restored the `before-1fc3fda-<timestamp>/database.dump` backup (taken
during `PUB-01`'s own upgrade, before any of this cycle's changes) into a
disposable `postgres:16.15` container on its own Docker network
(`restore-test-net`), entirely separate from the running production `db`
service and its volume:

- `pg_restore --no-owner --no-privileges` completed without error.
- Every table's row count in the restored instance exactly matched the
  pre-upgrade snapshot recorded in `pub_01_review.md` (`catalog_game` 39,
  `reviews_review` 12409, `summaries_summaryjob` 2, etc.) -- the backup is
  a genuine, complete, restorable snapshot, not just an archive that
  exists.
- The isolated container and network were torn down completely
  afterward; the production database was never touched by this test at
  any point (separate container, separate network, separate credentials).

## Storage forecast and AI backlog on real data

Ran this cycle's own `HRD-05` tooling against the live production
database for the first time on real, non-synthetic data (via
`docker compose exec web python app/manage.py storage_report` /
`diagnose --backlog`):

- Database size ~27.6 MB against 71 GiB free disk (VDS-level `df -h /`;
  see note below) -- effectively no near-term storage pressure at the
  current corpus size.
- `observations_per_review` 1.10, `versions_per_identity` 1.0,
  `attempts_per_terminal_job` 0.056 (2 of 36 terminal summary jobs ever
  needed a real provider call; the rest correctly resolved as
  `insufficient_data` with no call spent) -- real evidence the overhead
  ratios this tool exists to surface are modest at current scale, and
  that quota is being spent conservatively by design, not by accident.
- `diagnose --backlog`: 0 outstanding summary jobs, 165 pending review
  jobs (freshly discovered games still being worked through), 3
  retryable daily candidates -- a healthy, draining backlog, not a stuck
  one.
- **Known limitation, not a defect:** `storage_report`'s `--disk-path`
  is evaluated inside the `web` container's own filesystem namespace.
  Run against `/tmp` (that container's small `tmpfs` mount, per
  `compose.yaml`), it reports a meaningless 32 MiB total/free rather than
  host disk headroom. Real headroom for this report was cross-checked
  directly against the host via `df -h /` over SSH instead. A future
  cycle could bind-mount a real host path read-only into `web` for this
  specific purpose; not done here since it would weaken the container's
  otherwise-total filesystem isolation for a metric already obtainable
  directly from the host.

## Two consecutive real application hourly windows

- `run_id=4` (`scheduled:2026-09-15T19:00:00Z`): `succeeded`,
  `selected=20 processed=20 failed=0`, within minutes of `PUB-01`'s
  deployment.
- `run_id=5` (`scheduled:2026-09-15T20:00:00Z`): `succeeded`,
  `selected=20 processed=20 failed=0` -- the very next hour, genuinely
  consecutive. Subsequent ticks within that same hour correctly reported
  `skipped_duplicate` (idempotent, no repeated work), matching the exact
  behavior already verified deterministically in `HRD-02`/`HRD-03`.

Notably, the controlled host reboot above happened *between* these two
windows: the reboot command ran at `21:38:11 CEST` (`19:38:11Z`, after
`run_id=4`'s `19:00:00Z` slot had already completed) and the host was
back with all containers healthy by `19:48Z`, well before the
`20:00:00Z` slot. The scheduler still produced a clean, correct
`run_id=5` afterward with no manual re-trigger -- reboot persistence and
hourly-window continuity were verified by the same sequence of real
events, not two independent, best-case scenarios.

## Verification

No new code this cycle -- purely operational verification against the
live `PUB-01` deployment. Every check above was performed against the
real running production service (never a local/fixture double): two
genuinely consecutive scheduled hours succeeded, a real host reboot was
survived with zero data loss and zero manual recovery, a real backup
restored cleanly into fully isolated storage, and the `HRD-05` diagnostics/
storage tools were run against real production data for the first time
and produced sane, correctly-scaled numbers. This closes `PUB-02`.
