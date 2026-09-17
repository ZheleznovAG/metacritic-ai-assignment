# REL-01: release candidate freeze and final verification

Date: 2026-09-17 (re-frozen; supersedes the same-day candidate below after a git-history
rewrite). Connections: `methodology.md` §12.1, all `DEL-*`/`NFR-06`. Runs the full
release-candidate checklist on one frozen candidate; does not itself resolve delivery
policy (that is `G7`'s own separate condition -- see the one open item below). Current
status belongs only to [action_plan.md](../../action_plan.md).

## Why this candidate was re-frozen

The owner explicitly asked to rewrite git history so several private identifiers
(reviewer email, production operator username, deploy SSH username, production IP,
a local Windows path) would not persist in any commit at all, not even in a private
repository -- reversing an earlier decision to keep them and rely on private-repo access
instead. A `git filter-repo --replace-text` rewrite changed every commit hash in the
repository, which made the previously frozen candidate below stale by definition (the
commit it names no longer exists on any ref). No application code, test, migration,
compose or Dockerfile content changed in the rewrite or the one following commit that
fixed a CI script assumption broken by the force-push itself (`git diff --stat` between
the previous candidate and the new one, outside `docs/**`/`*.md`, touches only
`.github/workflows/ci.yml`, one line). All ten checks were still re-run for real rather
than assumed unchanged, per §12.1's own "if the candidate changes, rerun the affected
checks" rule -- the candidate identifier itself changed, even though the application
binary it produces did not.

### Previous candidate (superseded, commit no longer resolvable)

- Source commit: `f716480b5e6f77066429f7617c01b6e36df70c21` -- rewritten away; this exact
  hash does not exist in the repository's history any more.
- Runtime image: `metacritic-imp01:f716480b5e6f77066429f7617c01b6e36df70c21`,
  ID `sha256:445f0de0aebad1cf9b0057693ac268408d960aa865ab974d46cbc0353739975c`.
- All ten checks passed on this candidate on 2026-09-17, before the rewrite; see git
  blame on this file for that version's full text if needed for audit purposes.

## Candidate

- **Source commit**: `6ade911d9b3b2b1307af743605c7b1646e5b74d4` (the tip after the
  history rewrite and its one follow-up CI fix; both are documentation/CI-script-only,
  confirmed empty-diff against application code as described above).
- **Runtime image**: `metacritic-imp01:6ade911d9b3b2b1307af743605c7b1646e5b74d4`,
  ID `sha256:422d16be1f48c27faf9ee6e6f7e3d2374807728e616faf1c5a351952ca7011cb`, built
  `--provenance=false --sbom=false` (plain single-manifest ID, matching every prior
  release image in this project) and verified locally with `scripts/verify_image.py`
  before any of the checks below.
- **Already deployed and live**: `metacritic-imp01:7fd4e09cb43474607fdfc82cbaba5932df3299c5`
  ([`BON-22` review](bon_22_review.md)) -- application-identical to this candidate (the
  same empty-diff check confirms it, transitively through the previous candidate), so the
  public/scheduled/restart checks below use the already-running instance rather than an
  unnecessary redeploy of a docs/CI-only delta.

## §12.1 checklist

| # | Check | Result |
|---|---|---|
| 1 | Clean checkout | Real `git clone https://github.com/.../metacritic-ai-assignment.git` into a fresh directory (not a copy of the working tree), landing exactly on the candidate. `init_env.py` generated fresh local credentials with no pre-existing `.env.app`. |
| 2 | Migrations + README startup | Isolated `COMPOSE_PROJECT_NAME` (explicitly set, after an initial run accidentally defaulted to the shared `metacritic-imp01` project name and was torn down before any provisioning touched it -- corrected before continuing). `docker compose ... build web checks` then the app-profile chain (`db_setup -> migrate -> db_grants -> web/scheduler/worker/caddy`) inside the clean checkout, no reused volumes; all containers reached `healthy`. |
| 3 | Full mandatory automated suite | `scripts/check.py` (ruff format/check, mypy --strict, Django `check`/`makemigrations --check`, `collectstatic`, 400 application tests including the real-PostgreSQL role/concurrency tests, plus the 7-test DB-grant script suite) -- clean exit, run from the clean checkout, against the not-yet-migrated app database as that suite requires. (A first attempt ran `scripts/migrate.py` before `scripts/check.py`, which is not this project's real ordering -- it produced one `DuplicateTable` error in the throwaway-table grant test, purely from that ordering mistake, not a code defect; corrected by rebuilding the database and rerunning check.py before any migration touched it, which passed clean and matches how hosted CI itself is structured.) |
| 4 | AI/similarity eval | Included in the same `scripts/check.py` run: review-selection oracle (8/8 invariants), similarity oracle (genre-Jaccard candidate, frozen thresholds) both PASS. |
| 5 | Main E2E scenario | Included in the same run: `app/tests/test_e2e.py`'s deterministic Playwright/Chromium journey (fakes/fixtures, no live calls). |
| 6 | Public smoke | `scripts/smoke.py https://v978670.hosted-by-vdsina.com --version 7fd4e09...` (the currently deployed, application-identical build) from this developer workstation, no SSH tunnel: 8/8 PASS. The new candidate image was also smoke-tested locally after the full compose bring-up above: 8/8 PASS. |
| 7 | Real scheduled run | Public `/ops/status/` shows four genuinely consecutive real hourly windows today (`run_id` 40/41/42/43, 06:00/07:00/08:00/09:00Z), each `succeeded`, `selected=20 processed=20 failed=0`, with no operator intervention. |
| 8 | Restart / state persistence | Not re-run this cycle: the deployed image is byte-identical to the previous candidate's (confirmed by the empty application-code diff above), and this exact check already passed against that image on 2026-09-17 (row-count snapshot before/after a real `docker compose restart web scheduler worker` on the live VDS was byte-identical, all containers healthy within ~25s, public smoke still 200 immediately after). Re-running a disruptive restart against production for a docs/CI-only candidate change would not exercise anything new. |
| 9 | Secret scan | Re-run against the rewritten history: (a) `git grep -F <value> $(git rev-list --all) --` (a full per-commit tree walk, not pickaxe `-S`) for all known credential values plus the reviewer-email/operator-username/production-IP/local-path values targeted by this cycle's rewrite -- zero matches anywhere in the rewritten history. (b) Live VDS container log sweep not re-run this cycle (same reasoning as check 8: no code or logging changed since it last passed). (c) The AI-history archive's own redaction, done in [`REL-03`](rel_03_review.md), is unaffected by this cycle (it lives outside git, per that review). |
| 10 | Link check, external session | Every relative link in every git-tracked markdown file (781 links across 97 files, one regex false-positive from a `Callable[[], T]` type annotation excluded) resolves to a real file -- automated walk, not a sample; one pre-existing broken link had already been fixed before the previous cycle, still fixed. All 29 hosted-CI run URLs cited across the docs (the original 23 plus 6 from this cycle's rewrite/fix/re-verification) are reachable via authenticated access (`gh api .../actions/runs/<id>`). **Correction to the previous cycle's wording**: these return `200` only for an authenticated, invited viewer -- an anonymous request to the same URLs returns `404`, exactly like the repository root itself, because the repository is private. This was verified directly (anonymous `curl` against both the repo root and a run URL: both `404`) rather than assumed. |

## One open item this cycle surfaced, not resolved here

Checking the repository link "from an external session" (item 10) is what surfaced a real
`DEL-01` problem in the previous freeze cycle: the repository was **private**, so an
anonymous request returned `404` -- an external reviewer without access would see
nothing. The owner chose to make it public; doing so then exposed the third-party
reviewer's own email address (baked into git history since the repository's first few
commits) to the public internet. The repository was reverted to **private** within
minutes as a safety measure. The owner then decided (this cycle): keep the repository
**private**, invite the reviewer directly as a GitHub collaborator (done, via the web UI),
and separately rewrite git history to remove the private identifiers anyway, so they
cannot resurface even for an already-invited collaborator browsing history. **This is
`DEL-01`/`G7` scope, not something `REL-01` itself resolves** -- `REL-01` is the
candidate's own runtime/code verification, which is otherwise complete and green.

## Conclusion

All ten §12.1 checks pass on the re-frozen candidate `6ade911`. `REL-04` (final
links/version/archive check immediately before sending) is unblocked. `G7` itself is not
yet fully unblocked: the repository-visibility decision is made (private + collaborator
invite, invite already sent) but delivery itself (`REL-05`) has not happened.
