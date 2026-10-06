# LOCAL-01: retire public deployment and preserve the running local service

2026-10-06. Owner authorized migration to the computer, private loopback access,
and continued automatic discovery/review/AI processing. Requirements: DATA-01/02,
RUN-01, NFR-01/06; risks: R-TST-01 and R-EXT-01. Status belongs to action_plan.md.

## Exit criteria frozen before execution

- Stop server-side writers before a consistent PostgreSQL 16 dump and exact
  per-table counts. Export the current immutable runtime image, private configuration,
  credentials and historical backups. Verify server/local archive SHA-256 values.
- Restore into a fresh, independently named local Compose project/volume, preserving
  schema ownership, catalog/reviews/summaries/embeddings/processing state and operator
  accounts. Compare every table count before starting background writers.
- Publish HTTP only on 127.0.0.1. Publish no database port. Keep secrets and raw
  data exports outside Git; do not overwrite existing development databases/config.
- Verify image identity, HTTP/browser navigation, live scheduler/worker heartbeat
  and a real local processing outcome with external/provider limitations explicit.
- Stop the public application after local verification, preserving server volumes
  for recovery. Removing the rented VDS/billing is a separate irreversible action;
  a retained recovery copy must not be described as a terminated rental.
- Document reproducible start/stop/status/backup commands and sanitized evidence.

## Verification and adversarial review

Verified locally on 2026-10-06/07. [Independent observations](../evidence/local-01/verification.json),
[restoration comparison](../evidence/local-01/restore-verification.json),
[export checksums](../evidence/local-01/export-checksums.json),
[frozen table counts](../evidence/local-01/restored-counts.txt),
[actual Docker bindings](../evidence/local-01/private-bindings.json) and
[Chromium results](../evidence/local-01/browser.json) cover the criteria:

| Criterion | Evidence |
|---|---|
| Consistent complete export | All writers stopped; 13 transferred files passed server/local SHA-256 comparison; database, role globals, private config, historical backups, Caddy state and immutable image retained under ignored `.artifacts/service-export-20261006/` |
| Independent restoration | Fresh `metacritic-personal` volume; all 40 table counts and row fingerprints matched before writers; 2,484 games, 29,015 reviews, 10,106 summary records and the operator retained |
| Privacy and image identity | Actual ingress is only `127.0.0.1:18081`; no published DB port; three app processes use the exact saved `b1e4b4f` image; private configuration is ignored |
| Function and automatic collection | HTTP smoke 8/8; Chromium 12/12; fresh scheduler/worker observations; real manual run 498 processed 19/20 through the normal dispatcher; worker provider key present |
| Public retirement | Compose `down` without `-v` removed all project containers; three server volumes retained; external port 80 connection refused |
| Recovery commands | `start`, `status`, `backup` exercised; backup custom archive readable with `pg_restore --list`; documented `stop` preserves volumes |

Adversarial checks caught and corrected Docker Desktop's inability to publish the
port from an internal-only Caddy network. The binding verifier now requires an
actual nonempty loopback mapping, rather than accepting an empty mapping. Saved
development volumes/configuration were preserved. No full application suite was
rerun for this operational migration: the unchanged runtime's identity, restored
data, live browser behavior and real collection were checked directly.

Run 498's remaining failure is `IdentityConflict` for Football Agent, matching the
previous server limitation. No identity was silently rewritten. Summary record count
does not imply every record contains a generated AI summary. Provider quotas and
source availability still apply; automatic work requires the computer and Docker
Desktop to be running. A new paid inference/quality assessment was not performed.

The VDS rental remains active; stopping containers does not terminate billing.
Before deleting the VDS, retain the downloaded export on independent storage.
