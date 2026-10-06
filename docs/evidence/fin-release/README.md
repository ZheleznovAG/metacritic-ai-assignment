# FIN-RELEASE evidence

Source `edc0914`, 2026-10-05. [Verification](verification.json) records the canonical
container suite, hosted CI and fresh isolated browser journey. Screenshots below
show controlled fake inputs in a disposable database, not production data.

- [Catalog desktop](imp-07-fixture-list.png)
- [Game card](imp-07-fixture-card.png)
- [Game card at 320 px](ui-opt-02-card-320.png)
- [Monitoring desktop](bon21-monitoring-desktop.png)
- [Monitoring mobile](bon21-monitoring-mobile.png)

The 2026-10-06 [deployment](deployment.json) upgrades the existing application on
the corrected service host using a server-built image. Earlier fresh-install/VPN
assumptions described the wrong server and are superseded. No VPN configuration
is part of this deployment. Existing HTTP ingress and production data are preserved;
trusted TLS remains outstanding.

[Production browser checks](production-browser.json) cover saved catalog data,
search/filter/pagination, card return, monitoring, mobile overflow and heartbeat.
Production screenshots: [catalog](production-catalog.png),
[card](production-card.png), [mobile](production-mobile.png).
The source CI is independent of deployment and tests the same source SHA.

The subsequent [listing correction](ingest-correction.json) deploys `b1e4b4f`;
two real runs resume processing with one explicit source-identity conflict each.
[Capacity and cleanup audit](capacity.md) distinguishes saved application data,
rollback backups, obsolete build artifacts and measured working memory.
