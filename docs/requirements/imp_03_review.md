# IMP-03: batch selection and calendar cycle

Date: 2026-09-11 (UTC). Task `IMP-03`; requirements `RUN-01`, `SEL-01`, `SEL-02`, `SEL-03`, `NFR-01`, `NFR-02`, `NFR-03` (mechanism); risks `R-TIM-01`, `R-TIM-02`. Current status belongs to [action_plan.md](../../action_plan.md).

## Scope actually built

The full state model from [`research/feasibility/processing-state.md`](../../research/feasibility/processing-state.md) (`SPK-04`): `processing.ProcessingLease` (singleton, monotonic fencing token, 45-minute TTL), `processing.ProcessingRun` (unique `trigger_key`, business day fixed at acquisition, counters), `processing.CoreAttempt` (per-candidate claim/outcome), and `DailyCycle`/`DailyCandidate` extended to the real phase/cursor/retry machinery IMP-02 only stubbed. A `Selector` (`processing/selector.py`) implementing `SPK-04`'s 8-step deterministic batch algorithm; two new gateway methods (`list_new_releases`, `iter_browse`) with a matching real parser; a `processing/runner.py` that reuses `catalog.ingest`'s upsert core (extracted into `fetch_and_prepare`/`apply_game_dto`, IMP-02's regression suite untouched); a real scheduler (`processing/scheduler.py` + `manage.py run_scheduler` + `scripts/run_scheduler.py`) with its own dedicated `SCHEDULER_DB_USER` Postgres role (`SELECT/INSERT/UPDATE` only, no DDL) — closing the TODO `IMP-02`'s `scripts/ingest_game.py` docstring left open, and that script now uses the same role.

Explicitly deferred (per the plan's scope boundary): `OPS-02` (bonus manual trigger), AI-enrichment retry (`IMP-04`), chaos/fault-injection concurrency testing beyond the paper scenarios (`HRD-02/03`), the public back-to-back-hourly-windows proof (`PUB-02`), and a permanent `compose.yaml` scheduler service (`PUB-01`) — the scheduler is a locally-invoked script for now, matching `IMP-02`'s "prove the mechanism first, deploy later" pattern.

## Fixture provenance (built before the list parser existed)

Same non-negotiable rule as `IMP-02`: real sanitised fixtures before the parser, independently-authored expected values.

| Capture | UTC | Bytes | SHA-256 |
|---|---|---:|---|
| `https://www.metacritic.com/game/` (New Releases) | 2026-09-11T12:31:20Z | 963,836 | `41667CB57CCCA22CD19B40DDC51C3E4E75438C20094550FD0551D3BFA223FEF9` |
| `.../browse/game/all/all/all-time/new/?page=1` | 2026-09-11T12:31:29Z | 334,773 | `A1FC2632590653DDD924429D69154D40DB24CD8B68B3045CA90BEF5C0F287305` |
| `.../browse/game/all/all/all-time/new/?page=2` | 2026-09-11T12:31:29Z | 351,465 | `926352ABEA62A41314E8D17592C33176A8BF402466409369195419905C4F5C17` |
| `.../browse/game/all/all/all-time/new/?page=7429` (the last page number shown in page 1's pagination, fetched to observe the real exhausted-page marker directly) | 2026-09-11T12:34:25Z | 325,864 | `733EB7353F26301033CF6C9D6C38B2E28E678F41739B5CAB4D126DA42D4E7BE8` |

Captured with `metacritic-ai-assignment-imp03/0.1`, the same low-frequency single-request discipline as `IMP-01/02`. `app/tests/fixtures/metacritic/new_releases.min.html`/`browse_page_1.min.html`/`browse_page_2.min.html`/`browse_page_last.min.html` keep real product-card hrefs/titles verbatim (in real page order) with a minimal wrapper, and a minimised `__NUXT_DATA__` array (same technique as `IMP-02`: every slot not reachable from the game-title records actually read is nulled, values/positions of everything read are unchanged). `lists_expected.json` is the independently-authored oracle, read from the raw payload before `parse_new_releases`/`parse_browse_page` existed.

**New real contract findings, confirmed live and cross-checked across three separate page captures (1, 2, 7429):**
- The New Releases carousel's 20 `game-title` records occupy a contiguous range in `__NUXT_DATA__`; SEE ALL cards live under `data-testid="product-title"` with the game link as an ancestor `<a>`, 24 per normal page.
- `data-testid="pagination-arrow-next"` carries an added `c-navigation-pagination__item--disabled` class only on the last page (verified by fetching page 7429 directly) — confirmed as the real exhaustion signal, not assumed.
- **Every SEE ALL page's canonical/`og:url` is the same bare listing URL, with no `?page=` query string at all — true for pages 1, 2, *and* 7429 alike.** This first surfaced as a real bug during live verification (see below) before it was caught by a fixture; the fixtures were corrected afterward to the real captured canonical value once discovered, since they had been hand-built with a fabricated `?page=N`-suffixed canonical rather than the actual captured one.

## Exit-criterion audit

| Criterion | Independent evidence obtained | Remaining boundary |
|---|---|---|
| Deterministic `AC-SEL-01..06` coverage | `app/tests/test_processing_selector.py`: `PS-01` (first run ≤20 New Releases only), `PS-02`/`AC-SEL-02/03` (pagination + dedup across two pages), `PS-03` (item failure retryable, no backfill, retried first next run), `PS-04` (new day updates existing game without duplicate, old cycle kept), `PS-05` (run spanning midnight keeps its start-time business day throughout), `AC-SEL-06`/exhaustion (zero new candidates, no re-scan), `PS-09` (a failed next page does not advance the cursor past it) | `PS-11` (AI failure) is `IMP-04` territory — reduces to "`ReviewCollectionJob` state never touches `DailyCandidate`", proven structurally; `PS-12` (non-UTC business timezone) is not built — `ASM-01`'s UTC default is what ships, `DailyCycle.timezone` exists in the schema but nothing reconfigures it yet |
| `RUN-01`/`AC-RUN-01` mechanism (one run per hour slot, no duplicate/overlap work) | `PS-07`/`DuplicateTriggerTests` (same-hour tick is idempotent, zero extra fetches) and `PS-06`/`LeaseOverlapTests` (a second acquire while the lease is held raises `LeaseOverlap`) — **both also independently confirmed live** (see below): two real hourly boundaries in a row each fired exactly once, and a same-hour repeat `--once` returned `skipped_duplicate` with zero new HTTP calls | The full two-consecutive-*public*-hourly-windows proof is `PUB-02` |
| `NFR-01`/`AC-NFR-01` restart persistence | `PS-08`/`RestartRecoveryTests` (a candidate left `processing` by a simulated crash is swept to `retryable` by the next run's recovery step, then retried and succeeds) | Full fault-injection under a real killed process is `HRD-02` |
| `NFR-02`/`AC-NFR-02` partial failure isolation | `PS-03` plus **real evidence**: the first live run hit two genuine transient transport errors (`RemoteProtocolError`, `ConnectError`) on 2 of 20 games; both were retried automatically by the very next hourly run and succeeded, with the other 18 already-committed successes never touched | Broader failure taxonomy (malformed responses, timeouts under load) is `HRD-01` |
| `NFR-03`/`AC-NFR-03` concurrency dedup | `LeaseOverlapTests`, `DuplicateTriggerTests`, and a dedicated `test_a_lease_lost_mid_batch_backfills_accurate_counters_from_committed_attempts` proving `ProcessingRun` counters stay accurate (backfilled from committed `CoreAttempt` rows) even when the lease is lost mid-batch | Real concurrent OS processes/threads racing (vs. this session's controlled simulations) is `HRD-03` |

## Live runs against the real site (not just fixtures)

Two real scheduled ticks fired automatically, exactly at the real UTC hour boundary, with no manual intervention between them (`scripts/run_scheduler.py`, continuous mode, left running across the boundary):

| Run | `trigger_key` | `started_at` (UTC) | `ended_at` | status | selected/processed/failed |
|---|---|---|---|---|---:|
| 1 | `scheduled:2026-09-11T12:00:00Z` | 12:54:39 | 12:56:02 | `partial` | 20 / 18 / 2 |
| 2 | `scheduled:2026-09-11T13:00:00Z` | 13:00:14 | 13:00:24 | `partial` | 2 / 2 / 0 |

Run 1 (first run of business day 2026-09-11): fetched the real New Releases carousel (20 games), created 20 `DailyCandidate` rows, transitioned the cycle to `browse`. 18 of 20 core fetches succeeded; 2 (`Marsupilami 2 - Salsa Palombia`, `Wo Long: Fallen Dynasty - Complete Edition`) hit genuine transient transport errors and were left `retryable` — a real, unstaged instance of exactly the failure class `AC-NFR-02`/`PS-03` require handling. A same-hour repeat `python scripts/run_scheduler.py --once` immediately afterward returned `outcome=skipped_duplicate` against the same `run_id`, with no new HTTP requests — real `PS-07`/`PS-INV-01` confirmation.

Run 2 fired automatically at the next real hour boundary (retry-first, `PS-INV-05`/`ASM-05`): it picked up exactly the 2 retryable candidates from run 1 — both succeeded this time — and would have continued into SEE ALL discovery for the remaining capacity, except that a real bug (below) blocked discovery for this run; the cursor was correctly left un-advanced rather than skipping the failed page.

Across both runs: **93 `SourceFetch` rows** (1 `new_releases`, 25 `game_detail` succeeded + 2 failed, 64 `platform_userscore` succeeded, 1 `browse_page` invalid — the bug below), all via `scripts/run_scheduler.py` using the dedicated `SCHEDULER_DB_USER` role end-to-end. Run 2's own `browse_page` fetch is what surfaced the bug below, live. The scheduler process was killed and restarted *after* run 2 finished, to deploy the fix for subsequent ticks — the fix itself is confirmed by a direct live re-fetch-and-parse (below), not yet by a further automated tick; the next real hour boundary (14:00 UTC) was still in the future when this evidence was written and was not waited for, since the direct re-verification already gives independent proof the fix is correct.

## A real bug found live, not in a fixture

Run 2's SEE ALL discovery attempt failed with `MetacriticParseError`: the page's canonical URL (`https://www.metacritic.com/browse/game/all/all/all-time/new/`) did not match the requested `?page=1` URL, per the strict-equality canonical check built for `IMP-02`'s platform-userscore misroute protection. Investigating live (fetching page 1 directly and calling the parser against it) confirmed this is not a parser bug reacting to bad input — it's a genuine, previously-undiscovered fact about the source: **every SEE ALL page canonicalizes to the same bare listing URL, for every page number**, confirmed by directly re-checking pages 1, 2, and 7429 (all three raw captures already sitting in this session's fixture-building material showed the identical bare canonical — the fixtures had simply been hand-built with a fabricated `?page=N` canonical instead of reading the real captured value).

Fix: added `_require_matching_browse_listing` (path-only comparison, `metacritic/parser.py`), used only by `parse_browse_page`; `_require_matching_canonical` (exact-URL comparison) is unchanged and still used by `parse_game_detail`/`parse_platform_userscore`, where per-page canonical distinction is real and confirmed (the platform-userscore misroute case `IMP-02` built it for). A wrong/duplicate SEE ALL page landing here is still safe — caught by this module's identity-based dedup, not by canonical matching, which cannot distinguish pages of this specific listing. All three browse fixtures were corrected to their real captured canonical value. Re-verified live against a fresh fetch of the current page: `parse_browse_page` now returns 24 games, `has_next_page=True`, as expected. Because the scheduler process was only restarted with the fix after run 2 had already ended, no automated tick has exercised the corrected code yet as of this writing; the fix rests on this direct re-verification plus the (unchanged) unit tests, not on a third live run.

## Tests

- `app/tests/test_metacritic_lists_parser.py`: New Releases (all 20 cards, source order) and SEE ALL (page 1/2/last, overlap-in-this-snapshot check, real disabled-marker exhaustion, the corrected same-listing-canonical behaviour, missing-section/control failures).
- `app/tests/test_processing_selector.py`: 11 of the 12 `SPK-04` paper scenarios (see the exit-criterion table above for the two exclusions and why), plus a regression test for a run status bug found in adversarial self-review (below).
- `app/tests/test_processing_scheduler.py`: hour-slot rounding, trigger-key stability, fresh-hour run creation, same-hour idempotency, next-hour independence, and the lease-loss counter-backfill case.

80 Django tests total (53 carried over from `IMP-02`, unchanged and still green — the `catalog.ingest` refactor is behavior-preserving).

**A second bug found in adversarial self-review, before commit:** `Selector.run_batch`'s status derivation only classified a run as `failed` when the batch was *empty* (`processed_count == 0 and len(batch) == 0`). `processing-state.md`'s Run status table requires `failed` whenever there is no progress — including a non-empty batch where every selected item fails core processing — which the original condition silently mislabeled as `partial` instead. No existing test exercised an all-items-fail batch (`PS-03` only fails one of many), so this shipped undetected until a dedicated review pass checked the implementation against the spec's status table line by line. Fixed by dropping the `len(batch) == 0` clause (`elif processed_count == 0: status = "failed"`); `test_a_batch_where_every_item_fails_is_a_failed_run_not_partial` (`app/tests/test_processing_selector.py`) is the regression test.

## Verification commands

```powershell
uv lock
python scripts/check.py                        # ruff, mypy --strict, Django checks, makemigrations --check,
                                                 # collectstatic, 80 Django tests + the rest of the repo suite
python scripts/provision_db.py                  # adds the scheduler role
python scripts/migrate.py
python scripts/run_scheduler.py --once          # one real tick
python scripts/run_scheduler.py                 # continuous mode; ticks at least once a minute
```

`scripts/check.py` passed locally against the local dev PostgreSQL 16 container, using the `metacritic_checks` role's own isolated database — consistent with `IMP-01/02`'s role separation. This is local evidence, not a hosted CI run; the existing hosted CI workflow re-runs against this commit.

## Reproduction and pending input

No blocker. `IMP-04` (review pagination/collection, AI summaries — the batch this task builds now feeds real `ReviewCollectionJob` rows into it) is the next dependent on the critical path; `REV-EVAL-01`/`SIM-EVAL-01` remain independently available. `HRD-02/03` own the deeper fault-injection/concurrency evidence this task's controlled simulations point at; `PUB-01/02` own turning the scheduler into a permanent, publicly-deployed, continuously-running service.
