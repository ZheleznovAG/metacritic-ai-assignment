# PUB-03: external unauthorized user smoke

Task `PUB-03`. Requirements/risks per `implementation_plan.md#pub-03`:
from an external session on real data, list, combined search/filter/sort,
the full card, both summaries and navigation to a similar game all pass;
service version, run evidence and limitations are cross-checked; a
diagnosable pending state does not substitute for confirmed working AI
examples. Current task/gate status belongs only to
[action_plan.md](../../action_plan.md).

## Scope of this cycle

A real Chromium browser (Playwright, already a project dependency for the
deterministic `test_e2e.py` journey) drove the actual public URL directly
-- no SSH tunnel, no credentials, exactly what an unauthenticated visitor
gets. All five checkpoints from `AC-UI`/`PUB-03`'s own acceptance ran
against `game_detail.html`'s real CSS markers (`section.game-card__summary`,
`div.game-card__summary-claims`, `ul.similar-games`), not guessed text,
so a future template change that broke these markers would fail this
smoke the same way it would fail a real user.

## External smoke run

| Check | Result |
|---|---|
| List page returns `200` and shows real data (Elden Ring) | PASS |
| Combined search + platform filter (`?q=elden&platform=pc`) finds Elden Ring | PASS |
| Game detail card (`/games/1/`) returns `200`, title/developer correct | PASS |
| "Back to results" navigation link present | PASS |
| Exactly two summary sections present, headed "Critics" and "Users" | PASS |
| At least one summary renders real claims (`game-card__summary-claims`), not a pending/insufficient placeholder | PASS |
| No stale-summary placeholder shown for this freshly-processed game | PASS |
| At least one similar-game link present | PASS |
| Similar-game link (to "Elden Ring: Tarnished Edition") returns `200` | PASS |
| Landed page is that similar game's own real card | PASS |

All 15 individual assertions passed (`PUB-03 EXTERNAL SMOKE: ALL CHECKS
PASSED`). Sort itself has no separate control per `ASM-15` (rating order
is automatic); the search+filter check above exercises the same combined
query-string path `IMP-05`'s own tests already cover deterministically,
now against the live public instance's real, current catalog.

The similar-game match ("Elden Ring: Tarnished Edition") is a distinct
`Game` row the live scheduler discovered independently and linked purely
through saved shared genres -- not a seeded or fixture pairing -- directly
demonstrating `SIM-01`/`R-SIM-01` working end-to-end on organically
arrived data, not just the two games (Elden Ring/Wo Long) `SIM-VER-01`
originally verified with.

## Version, run evidence and limitations cross-check

- Service version: `APP_VERSION=1fc3fda...` (`PUB-01`'s deployed commit),
  confirmed via `verify_image.py` during that cycle; unchanged since.
- Run evidence: two genuinely consecutive real hourly windows
  (`pub_02_review.md`), diagnostics/backlog snapshot taken live
  (`pub_02_review.md`'s `diagnose --backlog` run).
- Limitations still open and correctly not hidden by this smoke: at the
  time of this run, TLS/DNS was still open (see update below) and 165
  review jobs were still draining from the fresh discovery backlog (a
  healthy, visible, diagnosable in-progress state -- not a blocking
  defect); 18 of the catalog's other games still without genre data
  (`SIM-VER-01`'s pre-existing, honestly-disclosed limitation).

## Verification

No new application code this cycle. The smoke script itself
(`pub03_smoke.py`, a local scratch file, not committed -- mirroring how
`deploy_release.py` and other one-off live-verification scripts from
prior cycles were never added to the tracked tree either) is real,
executable evidence of a real external run, not asserted from source
reading. This closes `PUB-03`'s own acceptance (external smoke on real
data).

**Update, same session:** at the time this smoke first ran, `G6` did not
yet close, since its own gate condition explicitly requires HTTPS/
external E2E and the deployment was still the HTTP-only preview. The
owner then provided a real hoster-provided hostname and asked for TLS to
be resolved within `PUB-01` (where `implementation_plan.md` actually
places the DNS/TLS requirement) -- see
`docs/requirements/pub_01_review.md`'s own "TLS/DNS" section for that
closure. With real, trusted HTTPS live, this exact 15-check script was
re-run against `https://v978670.hosted-by-vdsina.com` (not just asserted
to still work): all 15 checks passed again, the similar-game match this
time landing on a different, also organically-discovered title ("ARES:
THE IRON VANGUARD" -- the catalog kept growing between the two runs).
`smoke.py`'s own 8/8 HTTPS pass is recorded in `pub_01_review.md`. `G6`
is `Verified` in `action_plan.md` on this combined, now fully-HTTPS
basis.
