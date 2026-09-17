# REL-01: release candidate freeze and final verification

Date: 2026-09-17. Connections: `methodology.md` §12.1, all `DEL-*`/`NFR-06`. Runs the full
release-candidate checklist on one frozen candidate; does not itself resolve delivery
policy (that is `G7`'s own separate condition -- see the one open item below). Current
status belongs only to [action_plan.md](../../action_plan.md).

## Candidate

- **Source commit**: `f716480b5e6f77066429f7617c01b6e36df70c21` (the tip at the moment
  this cycle started; `git diff --stat` between it and every later commit in this same
  cycle, outside `docs/**`/`*.md`, is empty -- no application code, config or setup
  changed while finishing this review, so nothing needed re-verifying per §12.1's own
  "if the candidate changes, rerun the affected checks" rule).
- **Runtime image**: `metacritic-imp01:f716480b5e6f77066429f7617c01b6e36df70c21`,
  ID `sha256:445f0de0aebad1cf9b0057693ac268408d960aa865ab974d46cbc0353739975c`, built
  `--provenance=false --sbom=false` (plain single-manifest ID, matching every prior
  release image in this project) and verified locally with `scripts/verify_image.py`
  before any of the checks below.
- **Already deployed and live**: `metacritic-imp01:7fd4e09cb43474607fdfc82cbaba5932df3299c5`
  ([`BON-22` review](bon_22_review.md)) -- application-identical to this candidate (the
  same empty-diff check confirms it), so the public/scheduled/restart checks below use
  the already-running instance rather than an unnecessary redeploy of a docs-only delta.

## §12.1 checklist

| # | Check | Result |
|---|---|---|
| 1 | Clean checkout | Real `git clone https://github.com/.../metacritic-ai-assignment.git` into a fresh directory (not a copy of the working tree), landing exactly on the candidate. `init_env.py` generated fresh local credentials with no pre-existing `.env.app`. |
| 2 | Migrations + README startup | `docker compose ... build web checks` then the app-profile chain (`db_setup -> migrate -> db_grants -> web/scheduler/worker/caddy`) inside the clean checkout, isolated `COMPOSE_PROJECT_NAME`, no reused volumes. |
| 3 | Full mandatory automated suite | `scripts/check.py` (ruff format/check, mypy --strict, Django `check`/`makemigrations --check`, `collectstatic`, 400 application tests including the real-PostgreSQL role/concurrency tests) -- clean exit, run from the clean checkout. |
| 4 | AI/similarity eval | Included in the same `scripts/check.py` run: review-selection oracle (8/8 invariants), similarity oracle (genre-Jaccard candidate, frozen thresholds) both PASS. |
| 5 | Main E2E scenario | Included in the same run: `app/tests/test_e2e.py`'s deterministic Playwright/Chromium journey (fakes/fixtures, no live calls). |
| 6 | Public smoke | `scripts/smoke.py https://v978670.hosted-by-vdsina.com` from this developer workstation, no SSH tunnel: 8/8 PASS. |
| 7 | Real scheduled run | Public `/ops/status/` shows three genuinely consecutive real hourly windows today (`run_id` 40/41/42, 06:00/07:00/08:00Z), each `succeeded`, `selected=20 processed=20 failed=0`, with no operator intervention. |
| 8 | Restart / state persistence | Real row-count snapshot (`catalog_game` 580, `reviews_review` 13,097, `processing_processingrun` 42) taken, then `docker compose restart web scheduler worker` on the live VDS, then the identical snapshot re-taken: **byte-identical**. All three containers back `healthy`/running within ~25 seconds; public smoke immediately after restart still 200. |
| 9 | Secret scan | Three parts: (a) full `git log --all -p -S<value>` pickaxe search across every commit for all 11 known credential values plus the CI placeholder pattern -- zero real secrets found anywhere in history (only the `.example` template files were ever committed); (b) full container log sweep on the live VDS (`web`/`scheduler`/`worker`/`caddy`/`db_grants`, entire log history, not just a tail) for password/secret/API-key patterns -- zero matches, confirming `config/safe_logging.py`'s redaction holds in practice, not just in unit tests; (c) the AI-history archive's own redaction, done in [`REL-03`](rel_03_review.md). |
| 10 | Link check, external session | Every relative link in every git-tracked markdown file (738 links across 96 files) resolves to a real file -- automated walk, not a sample. All 23 hosted-CI run URLs cited across the docs return `200`. One real broken link was found and fixed *before* this cycle (`research/methodology/iteration_3/result/methodology.md`'s `assignment.md` link resolved to a nonexistent path relative to its own directory; fixed to the real repo-root path, pure link mechanics, no content change) -- see `f716480`'s own commit. The repository link itself was checked from a genuinely external, unauthenticated request (see the one open item below). |

## One open item this cycle surfaced, not resolved here

Checking the repository link "from an external session" (item 10) is what surfaced a real
`DEL-01` problem: the repository was **private**, so an anonymous request returned `404`
-- an external reviewer without access would see nothing. The owner chose to make it
public; doing so then exposed the third-party reviewer's own email address (baked into
git history since the repository's first few commits) to the public internet. The
repository was reverted to **private** within minutes as a safety measure, and the owner
was given the real tradeoff (rewrite history -- cascades to essentially every commit hash,
invalidating the hundreds of SHA citations this project's own documents rely on -- versus
keep it private and invite the reviewer as a collaborator by email, which needs no history
rewrite). The owner chose to decide later; full detail and the redaction fix already
applied to the AI-history archive are in [`REL-03`](rel_03_review.md)'s own updated
review. **This is `DEL-01`/`G7` scope, not something `REL-01` itself resolves** -- `REL-01`
is the candidate's own runtime/code verification, which is otherwise complete and green.

## Conclusion

All ten §12.1 checks pass on the frozen candidate. `REL-04` (final links/version/archive
check immediately before sending) is unblocked. `G7` itself is not yet unblocked: it still
needs the repository-visibility decision above resolved, independent of anything `REL-01`
verifies about the running candidate.
