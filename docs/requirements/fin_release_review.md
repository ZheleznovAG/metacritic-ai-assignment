# FIN-RELEASE: release and authorized production upgrade

2026-10-05, baseline `edc0914`; corrected deployment target on 2026-10-06.
The owner explicitly authorized an upgrade of the existing service and a
server-side build. The VPN server is excluded. Task/gate status belongs only to
[action_plan.md](../../action_plan.md). Requirements/risks: `DEL-01/02`, `NFR-01/06`,
`UI-01–05`, `OPS-01/02`, `R-TST-01`; research limits remain FIN-RESEARCH's limits.

## Exit criteria frozen before execution

- Canonical container build/suite, research freeze and image identity pass before
  switching production. Hosted CI uses the tested source revision.
- Fresh isolated processing-to-browser demo and desktop/mobile screenshots exist;
  production catalog/filter/pagination/card return/monitoring have browser smoke.
- Discover the selected target and preserve existing services. The earlier fresh-install
  assumption described the wrong host: the owner corrected `.env` and removed that
  installation. The actual target already runs the application. Back up its database
  and configuration, retain the prior image and preserve its host-specific ingress.
  Existing HTTP is retained for this upgrade; trusted TLS remains an unmet release
  criterion rather than being silently treated as verified.
- Deploy the exact verified source/image; migrations/grants, web/background process
  identities, public trusted-TLS smoke and real heartbeat/progress are checked.
- Release/tag, current README/snapshot and sanitized deployment evidence identify
  source SHA and image ID. Original submission history and research quality limits
  remain explicit. No production demo rows or fabricated run counters are inserted.

## Verification and adversarial review

The corrected-host upgrade passed source archive SHA-256 verification, runtime UID
readability/import checks, image identity in web/scheduler/worker, internal and
public HTTP smoke (8 checks each), and 12 external Chromium checks. Database and
configuration backups exist on the service host; the previous image remains.
No migrations or Compose changes exist between the old and new source versions.
Database and Caddy containers were not recreated. No VPN configuration is used.

Adversarial review checked the wrong-target counterexample, archive identity,
runtime file permissions, configuration/secret preservation, migration compatibility,
failure rollback, query continuity, mobile overflow and fresh background heartbeats.
An initial preflight imported ORM modules without Django setup; it failed before
stopping services and was corrected to check file readability and pure imports.

[Deployment evidence](../evidence/fin-release/deployment.json) and
[browser checks](../evidence/fin-release/production-browser.json) support the
upgrade. The published fixture demo remains separate from production data.
Trusted public TLS and release/tag completion remain outstanding; FIN-RELEASE
must stay In Progress. HTTP success does not reaccept historical G6.
