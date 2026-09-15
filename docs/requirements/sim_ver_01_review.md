# SIM-VER-01: saved similarity on game cards

Task `SIM-VER-01`; requirements `SIM-01–03`, `AC-SIM-01–03`, `AC-UI-06`;
risks `R-SIM-01`, `R-UI-01`. Current task/gate status belongs only to
[action_plan.md](../../action_plan.md).

## Implementation and evidence

`catalog.queries.list_similar_games()` takes a single SELECT snapshot of saved
IDs, titles and genre arrays, then calls the unchanged `genre-jaccard` 1.0.0 policy.
It returns IDs, matching snapshot titles, scores, shared genres and policy identity.
No platform join, source request, enrichment, provider call or write occurs. A
malformed manually stored JSON value is treated as unknown genres, not split
into invented features. Catalog-wide capacity remains a later operational check.

The card displays up to five results with their shared genres. Links use the
existing `game-detail` route and saved ID; the original `q`/`platform` parameters
survive each recommendation link and return to the list. No matches produces
an explicit empty state. Names/genres use normal template escaping, and long
source text wraps within the card.

| Acceptance boundary | Independent evidence |
|---|---|
| Relevance and order survive integration | `test_similarity_integration.py` seeds all 14 frozen catalogs in original and reversed insertion order and compares both DB results and rendered links to the published IMP-06 comparison; the frozen evaluator/report verifier also reruns |
| Saved-only, no self-match/duplicates, cap | Frozen cases plus platform multiplicity, deletion and missing query checks; no candidates can enter outside the SELECT snapshot |
| Correct ID navigation | Two equal-title records with distinct descriptions open their respective IDs; actual Chromium clicks exercise every fixture recommendation |
| Empty/unknown data | Empty/self-only catalog tests, unknown and malformed stored genres; browser checks all fixture cards |
| Query continuity and rendering | Integration round trip with Unicode/reserved query characters, template escaping; browser search/filter return and 390 px/desktop checks |

Local `scripts/check.py` passed: **292 application tests** (eight added), Ruff,
strict mypy on 108 source files, Django/migration/static checks and all offline
verifiers/integrity tests. The policy and frozen oracle are unchanged.
[Local verification excerpts](../evidence/sim-ver-01-verification.txt) record the run.

Chromium passed **56 fixture checks**, using a unique disposable PostgreSQL
database and read-only serving connections. No application database was seeded.
[Fixture report](../evidence/sim-ver-01-fixture-browser.json),
[desktop](../evidence/sim-ver-01-fixture-desktop.png) and
[mobile](../evidence/sim-ver-01-fixture-mobile.png) screenshots support the checks.
[Dated probes and reproduction](../../research/reviews/20260914_sim_ver_01/README.md)
remain research tooling, separate from deterministic application tests.

## Adversarial review

Self-review covered the acceptance table, `R-SIM-01`/`R-UI-01`, full oracle
continuity, equal titles versus identities, platform row multiplication,
missing/deleted games, malformed JSON, read-only behavior, HTML escaping,
query encoding, empty results and long text. Integration tests caught an initial
route-name mismatch in the new template; it was corrected before the passing run.
No separate reviewer or agent was used.

## Hosted CI and public verification

Candidate `408bd62bce72b2bfb6bfb53788b50bf9db618b28` was committed after local
verification and pushed to the project's `main` branch on 2026-09-15 after the
owner authorized continuation of the candidate/evidence push.
[Hosted CI 34929125538](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34929125538)
passed on that exact SHA at 2026-09-15 04:32:50 UTC: locked build, PostgreSQL
verification, offline runtime tokenization, Caddy startup and HTTP/CSS smoke.
The clean archived source built image
`sha256:d6f6e12fc9098089f70e4f4946c8e9632bfe543a6e3ea6d62ca166d86e18d914`.
The [release manifest and source-refresh snapshots](../evidence/sim-ver-01-release.json)
pin the source, image/config archive checksums, tested SHA and stable saved IDs.
After explicit owner authorization, the existing preview was upgraded with a
readable database backup and migration `catalog.0006`. Archive/image checksums,
all pre-existing table counts, credentials/settings and named volumes were
preserved; runtime identity, service health and HTTP/CSS smoke passed.
[Deployment output](../evidence/sim-ver-01-deployment.txt) records these checks.

Normal live ingestion of the existing Elden Ring (ID `1`) and Wo Long: Fallen
Dynasty - Complete Edition (ID `13`) supplied `action rpg` for both. Their distinct
successful source fetches `92` and `97` carry parser contract `1.1.0`, response
SHA-256 and timestamps. All 38 saved identities survived; no summary/provider
attempts were created. The [current saved snapshot](../evidence/sim-ver-01-public-snapshot.json)
records both reciprocal recommendations with score 1.0 and deployed source hashes.

Chromium passed **202 public checks** on all 38 real cards, comparing results and
linked titles to a separate DB snapshot and independent genre-set calculation.
The actual Elden Ring → Wo Long click opened `/games/13/`, retained the list
query/filter, and returned to the same search controls. Repeated rendering,
unknown-genre empty states and mobile/desktop layout passed.
[Public browser report](../evidence/sim-ver-01-public-browser.json),
[desktop](../evidence/sim-ver-01-public-desktop.png) and
[mobile](../evidence/sim-ver-01-public-mobile.png) screenshots record this build.

The other 36 real games retain unknown genres and show an honest empty state
until normal detail ingestion refreshes them. No demo records or title-derived
genres were added. The small synthetic quality set does not establish real user
satisfaction or large-catalog capacity. Full mandatory E2E, public AI summaries
and G4 remain owned by `IMP-07`; this similarity cycle made no AI calls.
