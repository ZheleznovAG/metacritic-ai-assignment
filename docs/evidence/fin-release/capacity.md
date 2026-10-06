# Service-host storage and memory audit

2026-10-06, FIN-RELEASE / NFR-01 / R-TST-01. Read-only inventory; existing files,
images, volumes and logs were not removed. Raw metadata and probe scripts stay in
ignored `.artifacts/server-capacity-20261006/`. Secret values are excluded from
published evidence. [Executable inventory snapshot](capacity-snapshot.json).
The processing incident interrupted the audit and is tracked as FIN-INGEST-01.

## Installation reconstruction

The Claude session dated 2026-09-24 records Ubuntu 24.04, one CPU, 2 GB RAM,
40 GB disk and preinstalled Docker 29.1.3. It added the deploy account and manual
Compose 5.5.1 plugin, built the application on the host and restored a database
with 1194 games and 27262 reviews. After installation it recorded approximately
7 GB disk used. This is a dated observation, not a pristine filesystem snapshot;
an exact package/file diff against a clean OS is unavailable.

The host now has the same application project, five running containers and three
used named volumes. Three exited-zero containers are the normal role provisioning,
migration and grant steps, not crashed application instances. No unrelated Docker
projects or orphan volumes were found. Existing enabled OS services are mostly the
Ubuntu image defaults; no system package removals are proposed without a baseline.
The manual Compose plugin is 32.3 MB; the legacy apt Compose wrapper also exists.

## Disk observations

The inventory before the incident correction measured 13,286,612,992 bytes used
on the 42,157,326,336-byte filesystem (about 12.37 GiB of 39.26 GiB).
After the additional fix build, rounded `df -h` remained 13G used / 25G available.

| Item | Observed size | Interpretation |
|---|---:|---|
| Docker image store | 9.072 GB initially; 9.299 GB after fix | Includes shared layers, compressed content and old builds |
| `/var/lib/containerd` | 9.274 GB during audit | Physical image/snapshot storage; overlaps Docker accounting |
| PostgreSQL volume | 241.9 MB initially; 242.2 MB later | Includes cluster, WAL and system databases |
| Application database | 133.25 MB | Saved application state, including indexes |
| `/home/deploy` | 248.61 MB before fix artifacts | Sources, incoming archives, configuration and backups |
| Backups | 146.61 MB before new fix backup | Dumps dominate; operational value exceeds their small size |
| `/usr` | 2.695 GB | OS, installed utilities and libraries |
| `/var/log` | 436.19 MB | Journald/authentication logs; not application data |
| `/var/cache` | 211.44 MB | OS caches |
| `/var/lib/apt` | 208.27 MB | Package metadata |

Rows overlap and must not be added. Docker's reclaimable summary was inconsistent
(144 MB initially and a negative value later), so it is not used as a reliable
cleanup estimate. Individual image sizes also share layers.

## Cleanup candidates, with retention boundaries

- Five initial unused checks/intermediate images were about 3.17 GB each, sharing
  layers. Their reported unique portions totaled approximately 6.58 GB. The fix
  adds another intermediate image. These are build artifacts, not application data.
- Older application releases: `614fc4a`, `e480f75`, `af598dae7c42`,
  `410ca3637d0c`, `a45bffa4aecd`, `7cbe906554a8`. Keep the current `b1e4b4f`,
  its immediate rollback `edc0914`, and preferably `5658162` until the correction
  has survived normal processing. Exact reclaimed bytes need post-cleanup measurement.
- Obsolete source trees `~/build` (20.2 MB), `~/ytp04-src` (13.7 MB),
  `~/ytp04-incoming` (34.4 MB), and later superseded release-build directories.
  They are not mounted by running containers. The live configuration directory
  `~/metacritic-ai-assignment-imp01` must be retained.
- Redundant October 3 dumps and the failed-preflight backup directory are small.
  Retain a readable current backup, a compatible prior backup and an off-host copy
  before defining a rotation policy. The new fix backup is additional to these sizes.
- `ytp04-incoming/env.worker.before` is an old credential-bearing file with mode
  0600. Its value was not read. Current `.env.app` and `.env.worker` are also 0600.
- System logs may be rotated under an explicit retention policy. Authentication logs
  account for tens of MB, while journals dominate. Docker logs already have bounded
  rotation: three files of 5 MB per container.

Do not classify an image as removable merely because it is tagged `<none>`:
the active PostgreSQL and Caddy images also appear that way in Docker accounting.
All three volumes are in use. Do not remove catalog/history rows as "old data";
they support saved results, provenance and recovery.

The audit accidentally pulled an additional Python base tag during the first disk
probe (about 190 MB virtual size); the corrected probe used the existing pinned
image ID. It is an additional cleanup candidate, not a system installation.

## Memory and CPU

Initial `free` reported 910 MiB used of 1967 MiB, with approximately 1057 MiB
available and no swap. Docker's working-set sample totaled about 490 MiB.

| Container | Initial working set | Initial cgroup lifetime peak |
|---|---:|---:|
| Web | 100.9 MiB | 112.0 MiB |
| Scheduler | 64.2 MiB | 66.1 MiB |
| Worker | 140.4 MiB | 141.8 MiB |
| PostgreSQL | 161.7 MiB | 288.9 MiB |
| Caddy | 23.2 MiB | 35.6 MiB |

Cgroup peaks are per-container, non-simultaneous and reset when a container is
recreated. They are not a historical host peak. All observed cgroup OOM counters
were zero. Worker inactivity during the listing outage understated normal demand.

After listing recovery, during real processing, working sets were web 104.5 MiB,
scheduler 80.3 MiB, worker 405 MiB, PostgreSQL 170.6 MiB and Caddy 17.5 MiB:
about 778 MiB for the containers. The host reported 1202 MiB used, 765 MiB available.
Earlier deployment diagnostics observed a worker working set of 486 MiB.
Summing per-process RSS would double-count shared PostgreSQL/library mappings,
so it is not used to estimate required host memory.

CPU is one core; idle load was around 0.06-0.08. In the active sample scheduler
used 17.8% and PostgreSQL 4.3%. This supports keeping one core for the observed
traffic, not a concurrency or stress-load certification.

## Capacity conclusion

Keep 2 GB RAM: observed real workload already exceeds 1 GB at the host level,
before build/dependency installation or other peaks, and swap is absent. A 1 GB
plan is not verified to support the unchanged service. Reducing disk to 20 GB is
reasonable after targeted cleanup and backup migration; roughly 6-8 GB total
steady storage is an estimate, not a measured post-cleanup state. Keep build
headroom and prevent accumulation of intermediate images. A 10 GB disk leaves
little room for host-side builds, updates, backup restore and catalog growth.

The current public [VDSina.com Standard prices](https://www.vdsina.com/pricing/standard)
list 1 CPU / 2 GB / 40 GB at $15 per 30-day month and 1 CPU / 1 GB / 10 GB at
$2.10. These are advertised prices, not the owner's account bill. Savings should
come from a cheaper 2 GB / approximately 20 GB offering, rather than assuming
this application's RAM requirement scales with low public request traffic.
