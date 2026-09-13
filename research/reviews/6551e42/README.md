# Implementation audit evidence: 6551e42

Reviewed implementation: `6551e42badb1bb98ae53c9772fd386620097301d`, 2026-09-13.
The [full report](../../../docs/requirements/implementation_audit_6551e42.md) maps
findings to requirements, code and correction exit criteria. Current task/gate
statuses belong only to [action_plan.md](../../../action_plan.md).

## Archived artifacts

- [reproduce.py](reproduce.py): the executed 24-probe harness, relocated from the
  ignored local review directory. Only its documented command and repository-root
  calculation were changed for publication; assertions are preserved.
- [observations.json](observations.json): all 24 `OBSERVATION` records parsed from
  the original successful probe run. Two confirm discovery corrections R02/R15;
  the other 22 reproduce defects grouped into 19 material findings.
- [verification.txt](verification.txt): verbatim selected output lines from local
  and Linux checks, probes and local HTTP checks; verbose output is omitted.
- [source_hashes.json](source_hashes.json): SHA-256 of original local review/probe
  files and logs. Originals remain in ignored `.artifacts/review-current/` on the
  author's machine. A hash alone does not reproduce a build or prove its success.

The original Markdown report was republished under `docs/requirements/` with
working archive links, publication notes and a correction queue. Its source hash
identifies the original review; it is not the hash of the published document.
No credentials, live review transcripts or provider envelopes are included.

## Reproduction

Use the repository's Python 3.12 `.venv-app` and local PostgreSQL setup from
[README](../../../README.md). From the repository root:

```powershell
.\.venv-app\Scripts\python.exe -B research/reviews/6551e42/reproduce.py
```

The harness refuses `APP_ENV=production`, selects `CHECKS_DB_USER`, and lets
Django create/drop `test_<POSTGRES_DB>_checks`. Do not run it concurrently with
other local/container database suites. Network source/provider calls are faked;
the quota counterexample uses two real PostgreSQL connections.

These assertions intentionally confirm **defective** behavior of the reviewed
implementation. `OK` is a successful reproduction, not product acceptance. After
a correction, corresponding probes are expected to fail: retain this historical
record and add desired-outcome regressions in `app/tests/`. Do not wire this
defect-confirming suite into CI as a required product gate. Existing CI runs the
application regressions through `scripts/check.py`.

The archived script must be run with its compatible reviewed implementation and
test helpers. Future schema/API changes can invalidate the harness independently
of fixing a finding; use the reviewed SHA to interpret such differences.
