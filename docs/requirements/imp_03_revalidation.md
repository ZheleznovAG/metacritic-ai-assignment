# IMP-03: scheduler revalidation after R02/R15/R16/R19/R20

Date: 2026-09-14 (Asia/Novosibirsk). Task `IMP-03`; requirements `RUN-01`, `SEL-01`,
`SEL-02`, `SEL-03`, `NFR-01`, `NFR-02`, `NFR-03`; risks `R-TIM-01`, `R-TIM-02`.
Current task/gate statuses belong only to [action_plan.md](../../action_plan.md).
This cycle revalidates the scheduler/selector after the discovery correction
([R02/R15](imp_03_discovery_correction.md)) and the ownership/retry and source
validation corrections ([R16/R20, R19](implementation_corrections_batch.md)),
none of which had been exercised against the real site since they were built
against fake gateways only.

## Local suite before any live call

Local dev PostgreSQL 16 (the same container used by the original `IMP-03` live
runs). `scripts/provision_db.py`/`scripts/migrate.py` applied five pending
migrations cleanly. `python -B scripts/check.py` passed before any live call:
263 application tests, 6 scripts, 18 planning, 7 AI-integrity, 9 selection and
14 similarity tests; format/lint/mypy/migration-drift/frozen-and-candidate
verifiers all green.

## Live run 1: a real bug found live, again

`scripts/run_scheduler.py` (continuous mode, dedicated `SCHEDULER_DB_USER`
role, same as the original `IMP-03`) was started at 09:40 UTC. The existing
local DB still held the original 2026-09-11 business day (41 games, cycle
`browse`, `browse_next_page=2`); a new UTC calendar day rolled the cycle over,
so the first tick fetched a fresh 20-game New Releases carousel for
2026-09-14 rather than resuming the old cycle. Run `scheduled:2026-09-14T09:00:00Z`
finished `partial`: 20 selected, 17 processed, 3 failed
(`serious-sam-shatterverse`, `bioeden`, `bus-simulator-27`), each with
`error_code=invalid_userscore` on an actual `200` `game_detail` response — not
the transient network class `PS-03` already covers.

Direct independent re-fetch and parse of all three pages (outside the
application, before touching the parser) reproduced the failure and found the
cause: `_extract_user_score` scanned the *entire* page for any tag whose
`title` matched `User score ... out of 10`, not just the actual hero/score-card
widget. For a brand-new game with too few ratings for an aggregate score,
Metacritic renders a second, unrelated widget elsewhere on the page whose
`title` literally reads `"User score null out of 10"` (a real templating
artifact — the correct hero widget nearby still says `"User score TBD"`).
`Decimal("null")` raised `InvalidOperation`, surfaced as `invalid_userscore`.
On the per-platform `/user-reviews/?platform=<slug>` page the same unscoped
scan is worse: for `serious-sam-shatterverse`'s `xbox-series-x`, the *only*
matching title on the live page belonged to one individual user's review card
(`"User score 0 out of 10"`), which the old code silently returned as if it
were the platform's aggregate Userscore — confirmed live: `parse_platform_userscore`
returned `Decimal("0")` for a platform that in fact has no aggregate score yet.

Fix (`app/metacritic/parser.py`): `_extract_user_score` now takes an explicit
list of containers and only scans tags inside them, instead of the whole
`BeautifulSoup` document. `parse_game_detail` scopes to `data-testid="global-score-wrapper"`
(the same testid already used for the real value in the passing `elden_ring`
fixture); `parse_platform_userscore` scopes to `data-testid="score-card-overview"`
and `global-score-wrapper` (both already used by this function's own
structural-presence fallback checks). Re-verified live immediately after the
fix: all three games parse cleanly with `metascore` set and `userscore=None`
(correct — none has enough ratings yet), and the `xbox-series-x` platform page
correctly returns `None` instead of the review card's `0`.

Two new regression tests (`app/tests/test_metacritic_parser.py`,
`LiveContractStrayUserScoreWidgetTests`) use two new minimised **live**
fixtures built the same way as every other fixture in this project — real
captured HTML, `__NUXT_DATA__` positions nulled except what the matching game
record actually reaches, unrelated widget markup kept byte-for-byte:
`bioeden_detail_tbd_userscore.min.html` (the stray `"...null..."` widget) and
`shatterverse_user_xbox_series_x_tbd.min.html` (the polluting review card).
Both were confirmed to fail against the pre-fix logic (manually replayed) and
pass against the fix. `app/tests/test_source_validation.py`'s existing direct
`_extract_user_score` unit test was updated for the new `list[...]` signature
only; its assertions are unchanged.

`python -B scripts/check.py` after the fix: **265** application tests (263 +
2 new), everything else unchanged and green.

## Live run 2: the real automated hour-boundary confirmation

The scheduler process was killed and restarted with the fix at 09:52:58 UTC,
before the next hour boundary, with no manual tick forced at the boundary
itself. `scheduled:2026-09-14T10:00:00Z` fired automatically at 10:00:16 UTC
and finished `succeeded` at 10:01:01: **20/20 processed, 0 failed** — the three
previously-`retryable` candidates succeeded this time (confirmed:
`serious-sam-shatterverse` metascore 48, `bioeden` metascore 64,
`bus-simulator-27` metascore 61, all with the correct `userscore=None`), and
the batch's remaining 17 slots were filled by SEE ALL discovery reading page 1
of the browse listing (`R02/R15`'s partial-page-checkpoint path): `DailyCycle`
stayed in `phase=browse`, `browse_next_page=1` — page 1 was only partially
consumed by the 20-item batch cap, so its checkpoint correctly stays put to be
reread (deduping already-accepted identities) on the next tick, exactly as
`imp_03_discovery_correction.md`'s fake-gateway regressions specify. This is
the first time that exact partial-page-checkpoint path has been exercised
against the real site rather than a fake gateway.

Across both runs: 227 `SourceFetch` rows (2 `new_releases`, 3 `browse_page` —
1 invalid from the original 2026-09-11 run, 2 succeeded here, 87 `game_detail`
— 82 succeeded + 3 invalid (pre-fix) + 2 failed (pre-existing transient rows
from 2026-09-11, untouched), 105 `platform_userscore` all succeeded). Catalog
now holds 60 games (41 carried over + 19 new from 2026-09-14) and 114
platforms. No AI/summary/review-collection call was made by this cycle; those
remain `reviews`/`summaries` app concerns already covered by `IMP-04`.

## Exit-criterion mapping (unchanged mechanism, revalidated on current code)

| Criterion | Evidence this cycle |
|---|---|
| Deterministic selection / dedup / retry-first (`AC-SEL-01..06`) | Unchanged 11+80 fake-gateway regressions still pass; live run 2 retried exactly the 3 real failures from run 1 before any new discovery, matching `PS-INV-05` |
| `RUN-01` one-run-per-hour-slot, no duplicate work | Run 2 fired automatically at the real 10:00 UTC boundary with the process left running unattended since before 09:53; no manual intervention at the boundary |
| Partial-page discovery checkpoint (`R02/R15`) | Live-confirmed for the first time: page 1 partially consumed, checkpoint retained at page 1, `browse_next_page` unchanged |
| Ownership/retry budget (`R16/R20`) | Not separately re-exercised live this cycle (no crash/stale-lease event occurred); unchanged 7 fake-gateway regressions in `test_processing_ownership.py` still pass |
| Source validation (`R19`) | Live-confirmed and *extended*: the existing Metascore/Userscore range checks fired correctly, and this cycle found and closed a real gap in userscore *extraction scope* the original R19 work did not cover |

`HRD-02/03`'s deeper fault-injection/concurrency evidence and `PUB-01/02`'s
permanent public scheduler deployment remain their own later tasks, unchanged
by this cycle — this revalidation only reruns the existing locally-invoked
scheduler mechanism against the real site on the current corrected code.

## Adversarial review

Reviewed the fix against both call sites and the two page types' structural
fallback checks. Concrete counterexamples checked: a genuinely-scored lead
platform must still resolve from within `global-score-wrapper` (re-verified
against the unchanged `elden_ring_detail.min.html` fixture, which was not
touched); a `global-score-wrapper`/`score-card-overview` container present but
empty of a numeric title must still return `None`, not raise, matching the
existing structural-presence contract; a container absent entirely must still
raise on the platform page (unchanged branch) and must not fabricate a lead
userscore on the detail page (falls through to `None`, matching the existing
`_extract_developer` soft-missing convention already used elsewhere in this
file). No change to `validation.py`'s numeric bounds themselves, `Metascore`
extraction, or any other field. `ruff format`/`ruff check`/`mypy --strict` all
pass on the changed file.

Historical incorrect `invalid_userscore` `SourceFetch` rows from before the
fix (2 from 2026-09-11, 3 from the pre-fix 09:00 run today) are retained as
history, not rewritten; the retained-score-provenance contract already proven
by `IMP-02` is what keeps stored data correct despite them.

## Boundaries and remaining scope

This is a mechanism-and-correctness revalidation, not new scope: the scheduler
is still a locally-invoked script (`PUB-01` owns making it a permanent,
publicly-deployed service); real fault-injection/concurrent-process racing
remain `HRD-02/03`; `IMP-04/05/06` are unaffected by this fix (they consume
`Game`/`GamePlatform` rows, and `userscore=None` for an unrated game was
already a valid, handled state throughout). No live AI/provider call was made.
