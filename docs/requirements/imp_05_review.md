# IMP-05: complete the mandatory user-facing flow

Date: 2026-09-12 (UTC). Task `IMP-05`; requirements `UI-01`–`UI-05`; risk `R-UI-01`. Current status
belongs to [action_plan.md](../../action_plan.md).

## Scope actually built

`catalog.queries.list_games()`/`list_platform_options()` (new): case-insensitive title substring
search, a platform filter, and the exact `ASM-15` sort rule — no filter uses the max Metascore
across *all* of a game's platforms; a filter uses the max among only the *matched* platform(s); a
game with no scored platform sorts after every scored one; ties sort by casefolded title.
`presentation.views.index` reads `q`/`platform` from the query string (stateless, no server-side
session — matches the `presentation` module's read-only boundary) and renders the real list;
`game_detail` echoes the same two params back as a "← Back to results" link, which is the entire
mechanism for `AC-UI-06`'s "open a result, return to the list, combination stays consistent" — no
new persisted state anywhere. `index.html`/`game_detail.html`/`app.css` got a real search/filter
form, a game-card grid with a placeholder for missing cover art and line-clamped long titles, and
light styling for `IMP-04`'s previously-unstyled summary sections.

UI-label language: **English, confirmed explicitly as the `ASM-14` fixed choice** (already the de
facto convention in every template since `IMP-01`/`IMP-04`; this cycle documents the decision
rather than changing anything — source review text and AI summaries stay untranslated regardless).

Explicitly deferred, matching `docs/design.md`'s own requirement-trace table, which lists
`UI-01–05`/`R-UI-01` evidence as jointly owned by **`IMP-05`, `IMP-07`, and `PUB-03`** — not `IMP-05`
alone: a public VDS smoke test against a redeployed live URL (`PUB-03` explicitly owns this later;
`IMP-01`'s VDS redeploy already proved the deployment mechanism, which this cycle doesn't change);
a full cross-browser matrix (`ASM-25` fixes current desktop Chromium as the only mandatory
acceptance environment); pagination (no `AC-UI` asks for it, and `AC-UI-01` itself just asks that
"each available game appears exactly once" — the list stays one deterministic, unpaginated page);
similarity/"similar games" UI (`IMP-06`/`SIM-*`, unrelated task, not built yet).

## Exit-criterion audit

| Criterion | Independent evidence obtained |
|---|---|
| `AC-UI-01` (every game appears once) | `test_presentation_index.py::IndexListTests::test_every_game_appears_exactly_once`; **live**: `/` against the 41 real games in the local dev DB rendered exactly 41 `game-list__item` cards |
| `AC-UI-02` (full card shows all fields + both summaries + honest missing-data states) | `test_presentation_game_detail.py` (`IMP-02`) + `test_presentation_summaries.py` (`IMP-04`, unchanged) still green; **live**: Elden Ring's card shows all 5 real platforms with natural `No data` cells and both summaries honestly `pending` (its corpus preconditions aren't met yet — see screenshots); Orbitals' card shows two real, complete Groq summaries with provenance |
| `AC-UI-03` (platform filter + reset) | `test_catalog_queries_list.py::PlatformFilterTests` (4 tests) + `test_presentation_index.py::test_platform_filter_narrows_and_reset_restores_the_full_list`; **live**: `/?platform=pc` narrowed the real 41 games to 34, reset (`/`) restored 41 |
| `AC-UI-04` (case-insensitive substring search + empty state) | `test_catalog_queries_list.py::SearchTests` (3 tests) + `test_presentation_index.py` (search-narrows, empty-state); **live**: `/?q=elden` against real data returned exactly the two real Elden Ring entries; `/?q=zzznotagame` showed the empty-state message |
| `AC-UI-05` (sort matches `ASM-15`, nulls after scored) | `test_catalog_queries_list.py::SortOrderTests` (5 tests, incl. the filtered-vs-unfiltered max-score distinction) + `test_presentation_index.py::test_sort_order_matches_asm_15_in_the_rendered_list`; **live**: `/?q=elden&platform=pc` showed Elden Ring's real PC Metascore (94), not its cross-platform max (96) |
| `AC-UI-06` (combined search+filter+sort stays consistent across navigation; long titles/missing media don't break the UI) | `test_presentation_index.py::BackToResultsRoundTripTests` (exact URL round-trip, not just "a link exists") + `test_a_long_title_and_missing_cover_do_not_break_the_response`; **live**: `/games/1/?q=elden&platform=pc`'s back-link is exactly `/?q=elden&platform=pc` |

166 Django tests total (up from 146 after `IMP-04`; 20 new tests are additive — every prior test
still passes unchanged, including one existing `IMP-01` test (`test_index_states_actual_scope`)
whose base class had to move from `SimpleTestCase` to `TestCase` now that `/` performs a real
database query — a mechanical consequence of the list becoming real, not a behavior change to what
it asserts).

## Live evidence and screenshots

Real local dev server, real 41-game catalog from `IMP-02`/`IMP-03`/`IMP-04`'s own live runs (no
seed/fixture data):

- `docs/evidence/imp05-list-preview.png` — `/?q=elden`: two real Elden Ring entries with real cover
  art and real Metascores (96, 90).
- `docs/evidence/imp05-card-preview.png` — Elden Ring's full card: 5 real platforms, the same
  natural `No data` Metascore for PlayStation 4/Xbox One `IMP-02`'s own evidence doc already
  recorded (a genuine source fact, not a regression), both AI summaries honestly `pending` (not all
  of Elden Ring's known routes have reached a terminal collection generation yet, so no corpus/
  summary exists — the honest state, not a bug).
- `docs/evidence/imp05-card-summary-preview.png` — Orbitals' full card: both audiences' real
  completed Groq summaries from `IMP-04`'s live run, rendered with model/generated-at/coverage
  provenance and no raw review text.

Captured with a one-off local `playwright` install (not added to `pyproject.toml`/`uv.lock` — this
session's `.venv` has it installed ad hoc for exactly this step, matching the plan's "no new
permanent dependency" call); no repo-committed screenshot tool exists yet, same as `IMP-01`'s own
precedent (`docs/evidence/imp01-preview.png`).

## Verification commands

```powershell
python scripts/check.py    # ruff, mypy --strict, migrations, 166 Django tests
python app/manage.py runserver 127.0.0.1:18081
# then exercise /, /?q=..., /?platform=..., /?q=...&platform=..., /games/<id>/?q=...&platform=...
```

`scripts/check.py` passed locally against the local dev PostgreSQL 16 container. This is local
evidence, not a hosted CI run; the existing hosted CI workflow re-runs against this commit.

## Reproduction and pending input

No blocker. `IMP-06`/`SIM-EVAL-01` (similarity) remain available independently. `IMP-07` (full
mandatory E2E) and `PUB-03` (public smoke, screenshot as part of a real external URL) are the next
owners of the remaining `UI-01–05` evidence this cycle's own local proof doesn't claim to cover, per
`docs/design.md`'s multi-gate trace table.
