# FIN-DOCS: documentation reconciliation

Scope: the 2026-10-05 roadmap documentation cycle, after FIN-ARCH (`3270226`).
Task and gate decisions belong only to [action_plan.md](../../action_plan.md).

## Exit criteria frozen before editing

- README provides a short, reproducible container entry point and links deeper commands.
- PROJECT_STATUS separates current code, original submission and recorded deployment;
  policy versions match executable source. No unobserved deployment or CI success is claimed.
- Existing requirement IDs, historical findings, frozen evaluation reports and gate
  decisions survive. Current limitations remain visible; a document is not its own evidence.
- ADR identities are unique, all renamed decision references resolve, and original
  decision identity is explained rather than silently rewritten.
- Monitoring/login/manual-trigger permissions agree with implemented boundaries.
- Planning integrity and documentation/source checks pass. Review checks misleading
  freshness, duplicated trackers, historical links and omitted operational commands.

## Verification and adversarial review

The review found and corrected these documentation defects:

- README denied login/mutations despite implemented operator endpoints and narrow grants.
- Original deleted-VDS URL was described as indefinitely live. Current docs now distinguish
  recorded deployment from availability; no new hostname or remote smoke is invented.
- The evidence index still treated delivery as future and Let's Play exclusion as current.
  Submitted scope/lateness remain historical; ADR-0005/0006 describe later experiments.
- Genre and Bonus 2 decisions shared ADR-0002. Genre is reindexed ADR-0007 with an
  explicit legacy-identity note; decision content, policy code and frozen hashes stay intact.
- Planning integrity depends on the exact `Bonus scope` baseline line. Its wording
  remains unchanged; current/experimental scope is explained separately, without
  rewriting accepted baseline dependencies.

Review boundary checks: original G4/G5/G6 records are retained; post-audit owner
reacceptance remains explicit in the tracker. No quality threshold is lowered.
Candidate wording in original Bonus 2/assumption planning text is identified as
historical, while executable evidence is linked separately. Archived commands and
incidents remain available, with relocated links and explicit historical notices.

Independent checks and reproducible commands:
[dated source audit](../../research/reviews/20261005_fin_docs/README.md),
[audit results](../evidence/fin-docs/audit.json),
[planning verification](../evidence/fin-docs/planning.txt).
Local path checks do not validate fragments, remote URLs or prose semantics; those
limits are disclosed rather than promoted to a global documentation proof.

[Canonical checks and smoke](../evidence/fin-docs/checks.txt) and
[verification record](../evidence/fin-docs/verification.json): final full container
suite passed (586 application + 22 script tests and offline evaluators), planning
negative-control suite passed 18 tests, local smoke passed 8/8. The first container
attempt's planning-format failure is retained in the excerpts; after restoring the
baseline field and rebuilding, the complete suite passed. Final documentation/evidence
was audited on the host; application and frozen evaluation source is unchanged.
A container/local pass does not verify hosted CI, current remote availability or a
new public release. No unresolved material documentation finding remains in this cycle.
