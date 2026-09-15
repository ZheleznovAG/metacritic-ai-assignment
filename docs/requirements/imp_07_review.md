# IMP-07: end-to-end journey, deterministic and public

Task `IMP-07`; closes gate `G4`. Requirements `RUN-01–03`, `SEL-01–02`,
`DATA-01–03`, `AI-01–04`, `UI-01–06`, `SIM-01–03`; risks `R-RUN-01`,
`R-AI-01`, `R-UI-01`, `R-SIM-01`. Current task/gate status belongs only to
[action_plan.md](../../action_plan.md).

## Scope

Two halves, both real: a deterministic fixture journey that exercises the
full scheduler → collector → worker → AI-provider → browser path with
controlled inputs and no live external services, and a public journey that
exercises the same code paths against real Metacritic, real Groq (within
free tier) and the already-deployed VDS application.

## Deterministic fixture journey

`app/tests/test_e2e.py` (`tests.e2e_scenario`): a real `processing.scheduler.run_tick`,
`reviews.collector`/`summaries.worker` state machines and the production
`summaries.groq_adapter` (fake HTTP transport) drive four fixture games from
zero rows to persisted `Game`/`ReviewSummary` rows — 4/4 candidates processed,
a repeat tick correctly `skipped_duplicate`, 12 review-page fetches reaching
`complete`/`empty` terminal state, 2 summary jobs (critic/user) `succeeded`.
A pinned Playwright Chromium session then drives a live Django server:
title-cased search, platform-dependent Metascore sort, the full card (cover,
developer, description, trailer, both platform rows with Metascore/Userscore,
both audience summaries with correct claim separation and provenance,
`3 of 3 fetched`), a real click into a similar game with query preserved,
"Back to results" restoring the exact search/filter state, and an honest
empty-results state. No unexpected network request occurred; the route
handler aborts anything outside the live server and one declared cover
fixture. Wired into `app/manage.py test tests` and the `checks` Docker image,
which now installs Chromium at build time (runtime image unaffected).

Two adversarial `/code-review high` passes over this half found and fixed
five real issues before/after commit: a missing `fetch_platform_userscore`
override in the fixture gateway (real ingest always re-fetches non-lead-platform
userscores via a separate call, discarding the DTO's initial value — the
fixture silently produced "No data" instead), a stale `scripts/smoke.py`
check tied to scaffold text this same diff removed from `index.html` (any
real deploy/CI smoke run would have failed), a dropped fast Django assertion
in `test_health.py`, a duplicated AI-provider response envelope in the test's
fake provider, and un-guarded Playwright teardown. All confirmed fixed by
`scripts/check.py` locally and in the Linux/PostgreSQL 16 `checks` image.
[Fixture verification](../evidence/imp-07-fixture-verification-2026-09-15.txt),
[container run](../evidence/imp-07-container-checks-2026-09-15.txt),
[list](../evidence/imp-07-fixture-list.png)/[card](../evidence/imp-07-fixture-card.png)/[mobile](../evidence/imp-07-fixture-mobile.png)
screenshots.

## Hosted CI and public deployment

Candidate `37b44fb924b6c2e56159e38ce0b854c55d11cc3f` passed
[hosted CI 34969484170](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34969484170)
(locked build, the full `checks` suite including the Playwright journey,
runtime startup through Caddy, image/CSS smoke) after one correction: the
first push failed `git diff --check` on trailing whitespace in a saved
evidence log, fixed in a follow-up commit and re-verified green.

The owner authorized continuing this candidate to the existing VDS preview.
Image `sha256:1a066e03c051b845429db8e36a2155dbc8ac80a91d40d723b47492460f67808d`
was built, exported, and its archive/config checksums verified identical
before and after transfer. The existing deployment was upgraded in place: a
readable `pg_dump` backup was taken first
(`backups/before-37b44fb-20260915T124135Z`), `init_env.py --upgrade-scaffold`
preserved all existing credentials/settings, `db_setup → migrate → web → caddy`
started healthy in 11.08s, before/after row counts for every pre-existing
table matched exactly, and the three named volumes
(`metacritic-imp01-prod_{postgres_data,caddy_data,caddy_config}`) were
confirmed unchanged by direct `docker volume ls` (the deploy script's own
`volumes()` re-check hit a script-level false negative — `db`/`caddy` were
never recreated in this cycle per unchanged `docker inspect .State.StartedAt`,
so the mismatch could not reflect real state; verified directly instead of
re-running the deploy). External HTTP/CSS smoke from a separate machine
(not through the SSH tunnel) against `http://<production-ip>:18081` passed
all 8 checks. [Deployment log](../evidence/imp-07-public-deployment-2026-09-15.txt),
[release manifest](../evidence/imp-07-release-manifest-2026-09-15.json).

## Real live scheduler, collector, worker, Groq

With the owner's explicit instruction to keep Groq usage minimal, a real
scheduler tick (`manage.py run_scheduler --once`, scheduler role, no AI
credentials, containerized with access to both the internal DB network and
the internet — the same pattern `sim-ver-01`'s live genre refresh used)
discovered and processed **19 real candidates from live Metacritic** in one
tick (`run_id=3`, `outcome=succeeded`, `processed=19`, `failed=0`), adding
one genuinely new game (catalog count 38 → 39). A real worker loop then ran
**401 ticks** (review-collection role + Groq credentials, same containerization
pattern) against live Metacritic and live Groq, capped to stop the instant
**2 real Groq HTTP calls** were reached (verified against `SummaryAttempt`
row count between ticks, not stdout parsing): 399 ticks were free live
review-page fetches — **12,409 real reviews collected**, 114 review-collection
routes reaching a terminal state — and ticks 399/401 were the two real,
capped Groq calls: critic and user summaries for the newly-discovered
"Brigandine Abyss", both `succeeded`. `insufficient_data`/`delayed_capacity`
outcomes never reach the provider HTTP call (checked in `summaries/worker.py`
before the request), so this cap is an exact bound on real provider spend,
not an estimate. [Scheduler tick](../evidence/imp-07-public-scheduler-tick-2026-09-15.txt),
[worker loop](../evidence/imp-07-public-worker-loop-2026-09-15.txt).

A real Chromium session then walked the live public site: search for the
new title, open its real card, and verify both audience summaries render
with correct provenance (`10 of 25 fetched` critic, `5 of 5 fetched` user,
`Model: openai/gpt-oss-20b`), no pending/insufficient-data placeholders, an
honest "No similar games in the catalog yet" (the new record's `genres` is
genuinely `[]` — no JSON-LD genre was present on this page, the same
documented non-fabrication behavior as `IMP-06`, not a defect), no page
errors, and no horizontal overflow at 390px. [Browser report](../evidence/imp-07-public-browser-2026-09-15.json),
[list](../evidence/imp-07-public-list.png)/[card](../evidence/imp-07-public-card.png)/[mobile](../evidence/imp-07-public-mobile.png)
screenshots. `SIM-VER-01`'s existing public evidence (Elden Ring ↔ Wo Long,
score 1.0) remains the live proof that the similar-games feature itself
returns real matches when genre overlap exists; this cycle additionally
confirms its honest-empty path on a brand-new record.

## Adversarial review

Covered in the fixture-journey section above (two independent `/code-review
high` passes, five real fixes). The public-path scripts (scheduler/worker
containerization, secret handling) are local operator tooling under the
gitignored `.artifacts/` directory, not shipped application code; the Groq
API key was transferred to the VDS directly by the operator into a
`600`-permission file the worker container read once at creation and which
was deleted immediately after, never appearing in any command this session
issued — enforced by the harness's own credential-leakage classifier, which
correctly blocked an earlier attempt to pass it inline.

## Summary

`IMP-07` is closed: the deterministic fixture journey and the real public
journey both prove the full `scheduler → collector → worker → AI provider →
browser` path end-to-end, with safe in-place upgrade, both audience
summaries, similar-games behavior (real matches via `SIM-VER-01`, honest
empty via this cycle), a full deterministic Chromium E2E, and a public
slice on real data. `G4`'s remaining condition — "все functional AC" — is
met by the union of `IMP-01`–`IMP-07`/`SIM-EVAL-01`/`SIM-VER-01`'s evidence;
no new functional gap was found.
