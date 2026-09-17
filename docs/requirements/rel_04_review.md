# REL-04: external verification of the public links and archive

Date: 2026-09-17. Connections: `methodology.md` §12.1, `DEL-01`–`DEL-04`. Verifies that
the repository, the public service, and the AI-history archive are actually usable by
someone who is not this development session, and that everything cites the same
candidate `REL-01` froze. Does not itself perform delivery (`REL-05`). Current status
belongs only to [action_plan.md](../../action_plan.md).

## Repository

- Anonymous, unauthenticated request to the repository root: `404` (checked directly with
  a plain `curl`, no cookies or tokens). This is the expected, already-documented state
  for a **private** repository (`DEL-01`), not a new finding.
- Authenticated access (this session's own `gh` credentials, and the `gh api` calls used
  for the CI-run check below) resolves the repository and every commit/run cited from it.
- **Limitation, stated plainly**: this review cannot log in as the invited reviewer's own
  GitHub account, so "external session" here means "genuinely unauthenticated" for the
  negative case (confirms private really means private) and "authenticated, not this
  session's local git checkout" for the positive case (confirms the invite grants real
  access), not a literal second human's browser. The collaborator invite itself was sent
  by the owner directly through the GitHub web UI ([action_plan.md](../../action_plan.md)
  2026-09-17 entry); this review did not re-send or re-verify delivery of that invite.
- Clean-checkout reproduction from this exact link is `REL-01`'s own check 1, re-run on
  the current candidate; not repeated here.

## Public service

- `https://v978670.hosted-by-vdsina.com/` from a plain anonymous request (no VPN, no SSH
  tunnel, no prior session state): `200`. `/health/live/` reports the currently deployed,
  application-identical build (`7fd4e09...`, matching [`BON-22`](bon_22_review.md) and
  [`REL-01`](rel_01_review.md)'s own empty-diff confirmation against the current
  candidate `6ade911`).
- `/ops/status/` (also anonymously reachable, by design -- `BON-21`'s public monitoring):
  snapshot at `2026-09-17T09:58:36Z` shows run `43` (`09:00Z`, `succeeded`,
  `selected=20 processed=20 failed=0`) as the latest of several consecutive real hourly
  windows already itemized in `REL-01`'s own check 7 -- consistent, no regression since.

## AI-history archive

Not independently hosted anywhere external -- `assignment.md` asks for it as an emailed
attachment alongside the repository link, not as a URL, so "external accessibility" does
not apply to it the same way. What this task owns instead, per its own specification, is
making sure the archive is current before it is ever attached to anything:

- Re-ran the full export/redact/package pipeline from the live Claude Code session logs
  (not a copy of the previous archive) immediately before this check, since session `10`
  (this ongoing session) had grown substantially during the `REL-01` history-rewrite/
  re-freeze cycle. Full detail, counts, and the two new redaction values added this pass
  (local Windows path, production operator username) are in the refreshed
  [REL-03 review](rel_03_review.md). New archive SHA-256
  `5505e0b74e8e31c7453caf3cca7459297dcbada6a40c67ce676f4727d19b936c`, 22,276 lines across
  11 files.
- This is still **not** the final cutoff -- session `10` continues after this export too
  (this very review is part of it). `REL-05` must re-run the same pipeline one more time,
  immediately before actually attaching and sending the archive.

## Metadata consistency with REL-01

- Every tracked document citing a specific candidate identity (`action_plan.md`,
  `docs/evidence.md`, `docs/requirements/rel_01_review.md`) names the same current
  candidate: commit `6ade911d9b3b2b1307af743605c7b1646e5b74d4`, image
  `sha256:422d16be1f48c27faf9ee6e6f7e3d2374807728e616faf1c5a351952ca7011cb`. The only
  remaining citations of the superseded `f716480`/`sha256:445f0de0...` pair are explicitly
  marked as superseded, in `action_plan.md`'s dated journal entry and `rel_01_review.md`'s
  own "previous candidate" section -- both intentional historical record, not live status.
- `assignment.md`'s SHA-256 (`26F4AD2B...` current, `C8987F68...` at intake) is recorded
  consistently in `intake.md`, the only place that pairing is asserted.

## Final dated link check

Re-ran the same automated walk `REL-01`'s check 10 used, after this cycle's own edits:
**783 relative links across 97 tracked markdown files**, all resolve to a real file
(one regex false-positive from a `Callable[[], T]` type annotation excluded, same as
`REL-01`). The 23 previously-cited hosted-CI run URLs remain reachable via authenticated
access; this task did not add new CI-verified commits of its own by the time of this
check (the review commit closing this task is verified separately, after it exists).

## Conclusion

Repository, public service, and archive are each in the state `REL-05` needs them in,
metadata is internally consistent with the re-frozen `REL-01` candidate, and the dated
link check is clean. `REL-05` (the actual delivery) is unblocked, with the explicit
carry-forward obligation to re-run the AI-archive export one final time immediately
before sending, not reuse this snapshot.
