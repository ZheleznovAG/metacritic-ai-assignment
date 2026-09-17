# Requirement → evidence index

`REL-02`. Maps every requirement ID from [requirements.md](requirements/requirements.md)
to the review/evidence document that actually verified it. This index only points at
evidence that already exists; it does not itself re-verify anything. Current task/gate
status and the authoritative dependency graph stay in [action_plan.md](../action_plan.md) —
if the two ever disagree, `action_plan.md` wins. `REL-01`/`REL-04` still need to run the
final acceptance pass across all of this; until then treat `DEL-01`–`DEL-04` as expected,
not Verified.

## Periodic run and selection

| ID | Requirement | Evidence |
|---|---|---|
| `RUN-01` | One scheduled processing run per UTC hour | [IMP-03 revalidation](requirements/imp_03_revalidation.md) (real automatic tick); [PUB-01](requirements/pub_01_review.md)/[PUB-02](requirements/pub_02_review.md) (supervised service, two consecutive real hourly windows across a host reboot); [BON-22](requirements/bon_22_review.md) confirms the hourly timer is unaffected by the new manual-run dispatcher |
| `SEL-01` | First daily selection is up to the first 20 eligible New Releases entries | [IMP-03 review](requirements/imp_03_review.md); [`processing/selector.py`](../app/processing/selector.py) tests |
| `SEL-02` | Later selections use SEE ALL in "Newest" order, skip today's already-processed items, advance sequentially | [IMP-03 review](requirements/imp_03_review.md) (live bug found and fixed: canonical SEE ALL pagination check) |
| `SEL-03` | A new business day restarts discovery from New Releases without deleting accumulated games | [IMP-03 review](requirements/imp_03_review.md); `processing.selector`/`DailyCycle` tests |

## Data and updates

| ID | Requirement | Evidence |
|---|---|---|
| `DATA-01` | First discovery creates the game; a later one updates the same game, never a duplicate | [IMP-02 revalidation](requirements/imp_02_revalidation.md) (5 consecutive live ingests, no duplicates) |
| `DATA-02` | Title, cover, developer, description, video link saved, or an honest absent-state | [IMP-02 review](requirements/imp_02_review.md); [HRD-01](requirements/hrd_01_review.md) (extraction failure vs. natural absence, executable contract) |
| `DATA-03` | Multi-platform games keep per-platform Metascore/Userscore | [IMP-02 revalidation](requirements/imp_02_revalidation.md) (Elden Ring, 5 platforms, verified fields) |

## AI review summaries

| ID | Requirement | Evidence |
|---|---|---|
| `AI-01` | Short critic-review summary, positives/negatives separated | [IMP-04 revalidation](requirements/imp_04_revalidation.md) (real grounded Groq summary); [REV-EVAL-01](requirements/rev_eval_01_review.md) (selection oracle) |
| `AI-02` | Short user-review summary, positives/negatives separated | Same as `AI-01`; both audiences confirmed on `/games/14/` in [IMP-04 review](requirements/imp_04_review.md) |
| `AI-03` | Summary can be refreshed on a material input/contour change, without forced regeneration of an unchanged result | [IMP-04 review](requirements/imp_04_review.md) (fingerprint cache-hit, `delayed_capacity`); [HRD-04](requirements/hrd_04_review.md) (frozen contour/quality eval) |

## Web interface

| ID | Requirement | Evidence |
|---|---|---|
| `UI-01` | Consistent list of loaded games | [IMP-05 revalidation](requirements/imp_05_revalidation.md); [SIM-VER-01](requirements/sim_ver_01_review.md) (202 public browser checks) |
| `UI-02` | Full card with the required contract and honest absent-data states | [IMP-05 revalidation](requirements/imp_05_revalidation.md); [IMP-07 review](requirements/imp_07_review.md) (deterministic Chromium E2E) |
| `UI-03` | Platform filter, correctly composed with search/sort | [IMP-05 review](requirements/imp_05_review.md) (`?platform=pc` narrowed 41→34; combined with search changed the shown Metascore as `ASM-15` predicts) |
| `UI-04` | Case-insensitive substring title search | [IMP-05 review](requirements/imp_05_review.md) (`?q=elden` → exactly 2 real rows) |
| `UI-05` | Single cross-platform sort rule, missing scores included | [IMP-05 review](requirements/imp_05_review.md) |

## Similar games

| ID | Requirement | Evidence |
|---|---|---|
| `SIM-01` | Up to the agreed limit of relevant, unique, self-excluding similar games | [SIM-EVAL-01](requirements/sim_eval_01_review.md) (frozen oracle, nDCG@5); [IMP-06](requirements/imp_06_review.md) (genre-Jaccard candidate accepted) |
| `SIM-02` | Similar games shown on the current game's card | [SIM-VER-01](requirements/sim_ver_01_review.md) (Elden Ring/Wo Long linked by real saved genres) |
| `SIM-03` | Clicking a similar game's name opens that game's own card | [SIM-VER-01](requirements/sim_ver_01_review.md); [PUB-03](requirements/pub_03_review.md) (public navigation to an independently-discovered similar game) |

## Bonus part 1 (not selected)

| ID | Requirement | Status |
|---|---|---|
| `YT-01` | Letsplay discovery/summary for each applicable game | **Dropped** — [ADR-0002](decisions/0002-bonus2-scope.md): owner selected the second bonus branch (operational monitoring/manual run), not YouTube; [BON-00 review](requirements/bon_00_review.md) |

## Bonus part 2 (selected)

| ID | Requirement | Evidence |
|---|---|---|
| `OPS-01` | Web UI shows real worker/processing state with consistent freshness | [BON-21 review](requirements/bon_21_review.md); public [`/ops/status/`](https://v978670.hosted-by-vdsina.com/ops/status/) |
| `OPS-02` | An authorized operator can force one processing run, without double-run or abuse | [BON-22 review](requirements/bon_22_review.md); [execution evidence](evidence/bon-22-public-deploy.json) (real manual run `id=36` on production, claimed by the live scheduler) |

## Delivery outcomes

| ID | Requirement | Evidence |
|---|---|---|
| `DEL-01` | Reviewer gets a reachable link to a reproducible repository | This repository; [Local development](../README.md#local-development) reproduces from a clean checkout. Final external link check belongs to `REL-01`/`REL-04`. |
| `DEL-02` | Reviewer gets a public link to a working service | `https://v978670.hosted-by-vdsina.com/` — live, real Let's Encrypt TLS ([PUB-01](requirements/pub_01_review.md)), kept running for as long as the review is ongoing (no fixed end date). Final external public smoke belongs to `REL-01`/`REL-04`. |
| `DEL-03` | The fullest available AI-assisted history, original order, raw JSONL acceptable | [REL-03 review](requirements/rel_03_review.md): 10 sessions, 20,328 lines, redacted and verified, one honestly-documented gap (no local session log before 2026-09-11). The archive still needs a cutoff/privacy refresh in `REL-04` to fold in the release-verification sessions that happen after this point, before it is actually sent. |
| `DEL-04` | The reviewed package is sent to the assignment's email address | `REL-05` (not yet due) |

## Derived non-functional properties

| ID | Requirement | Evidence |
|---|---|---|
| `NFR-01` | Game data and daily progress survive a process/deployment restart | [PUB-02 review](requirements/pub_02_review.md) (real host reboot, all 5 supervised containers recovered, row counts preserved) |
| `NFR-02` | One game's or one AI job's failure never rolls back others' confirmed progress; a failed item can be retried | [HRD-02](requirements/hrd_02_review.md) (stranded-run resume); [HRD-04](requirements/hrd_04_review.md) (transport-failure isolation) |
| `NFR-03` | Overlapping scheduled runs and redelivered retries never double-process or duplicate | [HRD-03](requirements/hrd_03_review.md) (real two-thread PostgreSQL races on the lease and both job queues); [BON-22](requirements/bon_22_review.md) extends this to scheduled/manual races |
| `NFR-04` | External HTML is validated; a partial/malformed response never corrupts state and surfaces visibly | [HRD-01](requirements/hrd_01_review.md) (bounded response size/time, retry only for transient failures, extraction-failure vs. natural-absence distinction) |
| `NFR-05` | Each run exposes time, outcome, counters and error-to-run/game linkage | [HRD-05](requirements/hrd_05_review.md) (`processing/diagnostics.py`, `scripts/diagnose.py`); [BON-21](requirements/bon_21_review.md) (public `/ops/status/`) |
| `NFR-06` | Clean-checkout reproducibility; no secrets in code/logs/published material | [HRD-05](requirements/hrd_05_review.md) (API-key redaction, escaping); [scripts/tests/test_database_roles.py](../scripts/tests/test_database_roles.py) and [test_database_roles_manual_run.py](../scripts/tests/test_database_roles_manual_run.py) (real PostgreSQL permission boundaries); final clean-checkout run belongs to `REL-01`/`REL-04` |

## Setup, test and deploy commands

Consolidated from the sections below they're each documented in full:

- **Local setup and run**: [README.md § Local development](../README.md#local-development).
- **Full offline verification** (`ruff`/`mypy`/Django tests/evals): [README.md § Verification and container preview](../README.md#verification-and-container-preview) — `python -B scripts/check.py`.
- **Container/CI parity**: same section — `docker compose ... build web checks`, `docker compose ... run --rm checks`, `docker compose ... --profile app up -d --wait`, `scripts/smoke.py`.
- **Production deploy/upgrade**: [deploy/README.md](../deploy/README.md) (backup-first, image identity verification, `db_setup -> migrate -> db_grants -> web/scheduler/worker -> caddy`, TLS).
- **Operator provisioning (BON-22)**: `docker compose ... run --rm --no-deps migrate python app/manage.py create_operator <username>` — [README § Manual run](../README.md#manual-run-bon-22).
- **Diagnostics**: `scripts/diagnose.py`, `scripts/storage_report.py` — [README § Operations](../README.md#operations).

## Schedule, scope and limitations

- All processing/monitoring timestamps are **UTC**; the scheduler checks the current hour
  slot at least once a minute ([design.md](design.md)).
- In scope: automatic hourly discovery, critic/user AI summaries, catalog UI with
  search/filter/sort, similar games, operational monitoring (`OPS-01`) and a protected
  manual-run trigger (`OPS-02`, both bonus-part-2 scope per [ADR-0002](decisions/0002-bonus2-scope.md)).
- Out of scope (bonus part 1, dropped): YouTube letsplay discovery/summary (`YT-01`).
- Known limitations are recorded where they were found rather than summarized separately
  here, to avoid a second, driftable copy: see each review document linked above, and
  [risks.md](risks.md) for the accepted residual risk register.

## Availability

The public deployment at `https://v978670.hosted-by-vdsina.com/` is kept running for as
long as the review is ongoing; there is no fixed decommission date. `scheduler`/`worker`
keep processing automatically in the background the entire time (`PUB-01`/`PUB-02`).
