# IMP-05: public UI revalidation and long-title correction

Observed on 2026-09-14 UTC. Requirements `UI-01`–`UI-05`, `AC-UI-01`–`AC-UI-06`,
`AI-03`; assumptions `ASM-14/15/25`; risk `R-UI-01`. Current task and gate
statuses belong only to [action_plan.md](../../action_plan.md).

## Public observation and independent oracle

The initial public preview reports build `92c846a3a5e6a84b0798633c97f74f23104d97c4`,
image `sha256:f5e92182298388c8937c96054fb524979de0afde048696d98c519f850162b109`.
Its actual catalog has grown to **38 games**, with **76 pending summary sections**.
The older one-game observation from IMP-02 is not the current catalog.

A [read-only database snapshot](../evidence/imp-05-public-db-2026-09-14.json)
was obtained through the running web container's restricted role. It contains
catalog fields, platform memberships/scores, summary metadata and source hashes;
it contains no raw reviews, credentials or private host address. Expected listing
membership and order were calculated from these stored fields without invoking
`list_games()`. All seven queried Python/template source files match local HEAD
`88b933f`; the CSS matched before this cycle's correction.

[Browser observations and artifact hashes](../evidence/imp-05-revalidation-2026-09-14.json)
record **50 passing public checks** in Chromium `151.0.7922.34`: the entire list,
three platform filters, case-insensitive partial search, combined search/filter,
card and return navigation, empty/reset states, CSS, loaded cover, five real
platform rows and natural missing scores. Elden Ring's card fields also match
the independent source oracle published in IMP-02. Desktop is 1280 px wide;
mobile is 390 px. No browser script errors or horizontal overflow occurred on
these real public pages.

## Boundary finding and correction

A separate nine-game fixture includes opposite filtered/unfiltered rankings,
equal scores with differently cased titles, zero and null scores, no platforms,
missing media and a **255-character title without spaces**. The last case passed
the existing HTTP-response assertion but overflowed the mobile card in a real
browser. `overflow-wrap: anywhere` on `.game-card` now allows long text to wrap
inside the card, preserving the full title.

After rebuilding static files, the same browser probe passed **35 checks**.
The long-title card now has `scrollWidth=390` at viewport width 390. The fixture
database is isolated, and the HTTP connections use PostgreSQL read-only
transactions. Summary fixtures go through the real collector/corpus/worker with
fake external adapters: fresh cached output displays current coverage (10 of 11),
new collection marks both old results stale, and insufficient-data explanations
survive the stale state. Content-only trailer fallback also renders correctly.
No live Metacritic or AI calls were needed for these fixtures.

## Exit-criterion audit

| Criterion | Evidence |
|---|---|
| `AC-UI-01`: every game once | Public DOM matches all 38 DB IDs, titles and scores; fixture covers nine distinct games |
| `AC-UI-02`: fields, both audiences, honest states | Public Elden Ring source-oracle comparison and two pending sections; fixture fresh/stale/insufficient checks; `test_presentation_game_detail.py`, `test_presentation_summaries.py`, `test_summary_freshness.py` |
| `AC-UI-03`: platform filtering and reset | PC/PlayStation 5/Xbox One public lists match DB membership and independently calculated score order; reset restores the initial list |
| `AC-UI-04`: partial, case-insensitive search and empty result | Public `ELDEN` search and `ELDEN`+PC; fixture mixed-case search; unknown query and unknown platform both give an explicit empty state |
| `AC-UI-05`: filtered/unfiltered max, ties, nulls | Public full-list/filter order checked against DB; fixture changes Alpha's score from 95 to 40 and places zero before null/no-platform games; case-insensitive tie order asserted |
| `AC-UI-06`: navigation and layout boundaries | Real form submission, card click, Back to results and reset; query/filter retained; 255-character unbroken title, missing core fields and cover; desktop/mobile screenshots |
| `ASM-14/25` | English labels retained; source content unchanged; Chromium desktop plus narrow-screen checks |

Screenshots: [public list](../evidence/imp-05-public-list-2026-09-14.png),
[public card](../evidence/imp-05-public-card-desktop-2026-09-14.png),
[public mobile card](../evidence/imp-05-public-card-mobile-2026-09-14.png),
[mobile filter](../evidence/imp-05-public-filter-mobile-2026-09-14.png),
[fixture list](../evidence/imp-05-fixture-list-desktop-2026-09-14.png),
[fixture mobile list](../evidence/imp-05-fixture-list-mobile-2026-09-14.png),
[fresh/insufficient](../evidence/imp-05-fixture-fresh-mobile-2026-09-14.png),
[stale/insufficient](../evidence/imp-05-fixture-stale-mobile-2026-09-14.png),
[corrected long title](../evidence/imp-05-fixture-long-title-mobile-2026-09-14.png).

## Adversarial review and verification limits

Self-review checked requirements, risk `R-UI-01`, source/build identity, database
oracle independence, filtering changes to ranking, no-data vs zero, stale cache
coverage and return navigation. The substantive layout finding was corrected.
Two probe assumptions were corrected against observations: the public catalog
had grown beyond one game; real POST requests are rejected by CSRF with 403
before reaching the view's 405 guard. Both are recorded as probe corrections,
not application fixes. No separate reviewer or sub-agent was used.

[Verification excerpts](../evidence/imp-05-verification-2026-09-14.txt) record
266 application tests, format/lint/types/migration/static checks and all offline
verifiers passing before the CSS-only correction. Static collection and browser
checks were repeated after it. The unchanged application regressions already
cover summary state transitions and query behavior; a test asserting CSS text
would not establish layout correctness.

Public ready/stale AI summaries, similarity,
full mandatory E2E, HTTPS and later operational gates remain owned by their
respective tasks. This cycle does not claim those later outcomes.

## Hosted CI and final public upgrade

Candidate `5a038d4703cbabc11fec07644dcb1f9e4b172558` passed
[hosted CI 34837423748](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34837423748),
including locked builds, PostgreSQL offline checks, restricted runtime tokenization,
Caddy startup and HTTP/CSS smoke. A clean `git archive` of that same SHA built
runtime image `sha256:57a3713123f729dabdb5417ec474b245575a9fa9466c1b1fab3a5a7c9265ffab`.
The [release manifest](../evidence/imp-05-revalidation-2026-09-14.json) records
source/config/image archive hashes and sizes.

The existing preview was upgraded using the documented procedure. Archive
checksums matched before import; a readable database backup was retained;
existing credentials, settings and named volumes were preserved. Migration
`summaries.0003_summaryattempt_fencing_token_and_more` was applied by the normal
migration service. All pre-existing table counts, all 38 games' fields and
platforms, and their summary metadata remained unchanged. Web runs as
`65532:65532` with a read-only filesystem, and the three services are healthy.
[Deployment output](../evidence/imp-05-deployment-2026-09-14.txt) records the checks.

All **50 public browser checks passed again** on the new build. The served CSS
SHA-256 is `27f0e1d4b6fd8b763acf747f9364c92d6fbc5c8bf03740941c614d58555b87e1`,
identical to the corrected CSS exercised by the fixture probe. The linked public
screenshots now show this final build; initial observations and their screenshot
commit are preserved in the JSON report. The source and final evidence commits
are both checked by the same hosted workflow. No task beyond IMP-05 was started.

Dated probes and reproduction instructions are in
[research/reviews/20260914_imp05](../../research/reviews/20260914_imp05/README.md).
