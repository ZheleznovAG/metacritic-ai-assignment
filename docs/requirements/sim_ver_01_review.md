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

## Adversarial review and remaining verification

Self-review covered the acceptance table, `R-SIM-01`/`R-UI-01`, full oracle
continuity, equal titles versus identities, platform row multiplication,
missing/deleted games, malformed JSON, read-only behavior, HTML escaping,
query encoding, empty results and long text. Integration tests caught an initial
route-name mismatch in the new template; it was corrected before the passing run.
No separate reviewer or agent was used.

Hosted CI and public deployment/source-refresh/navigation evidence must be recorded
before task completion. Existing public rows initially have unknown genres until
migration `catalog.0006` and normal successful ingestion supply them. This cycle
does not infer genres from titles or silently populate demo records in the preview.
The small synthetic quality set does not establish real user satisfaction or
large-catalog capacity. Full mandatory E2E and G4 remain owned by `IMP-07`.
