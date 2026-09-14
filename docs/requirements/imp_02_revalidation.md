# IMP-02: real public ingest and retained-score provenance

Date: 2026-09-14 (Asia/Novosibirsk). Task `IMP-02`; requirements `DATA-01–03`,
`UI-02` (core card fields), `NFR-04`; risks `R-ID-01`, `R-DAT-01`, `R-EXT-03/04`.
Current task/gate statuses belong only to [action_plan.md](../../action_plan.md).

## Independent source observation and public ingest

The existing [Elden Ring fixture and expected values](../../app/tests/fixtures/metacritic/elden_ring_expected.json)
were authored before the parser, as recorded in [the original review](imp_02_review.md).
Those frozen inputs were not changed. Five sequential direct HTTPS GETs on
2026-09-14 independently checked the current detail and four non-lead platform
pages before the first public ingest. This observation code did not import the
application parser or ingestion code. Structured source IDs, score values, cover,
developer, both trailer URLs and the full description hash matched the old oracle.

[Sanitised observations and database snapshots](../evidence/imp-02-revalidation-2026-09-14.json)
include capture timestamps, response hashes and the original oracle file hash.
They are dated live evidence, not replacement parser fixtures. Raw pages and full
description/review text are excluded from the structured evidence files; screenshots
show the actual rendered card.

The public VDS initially ran source `8c766154fb147806fc67576f730b06f56aa04f03`.
Current repository source `d093ee2c2602ecb2fb0da01929d0520bda562241` differed only in
documentation and had successful [hosted CI 34804900760](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34804900760).
Read-only preflight verified the running image and absence of scheduler/worker
processes. Two disposable containers executed the shipped
`python -B app/manage.py ingest_game https://www.metacritic.com/game/elden-ring/`
against the VDS database using only the scheduler DB login. They used the existing
backend/edge networks, a read-only filesystem, dropped capabilities and no published
port. The temporary environment file was removed; the permanent web configuration
and its read-only DB role were preserved. No worker or AI provider was invoked.

| Public run | Game | Platforms created/updated | Jobs created | Total games/platforms/jobs |
|---|---|---|---|---|
| First, 04:43:36–04:43:42 UTC | ID 1, created | 5 / 0 | 10 | 1 / 5 / 10 |
| Repeat, 04:43:48 UTC | Same ID 1, updated | 0 / 5 | 0 | 1 / 5 / 10 |

Both runs retained one alias and one processed manual candidate. All game, platform,
alias, candidate and collection-job IDs remained stable on repeat. Ten actual
source requests have successful HTTP 200 evidence with individual response hashes.
The game is `metacritic/1300501979`; its developer is From Software and its complete
1059-character description has SHA-256
`9827979e11749766a52d79e20e6935816ebf6d8e700d3437c58b75ca428832b6`.

| Platform | Metascore | Userscore |
|---|---:|---:|
| PC | 94 | 7.6 |
| PlayStation 4 | No data | 7.5 |
| PlayStation 5 | 96 | 8.4 |
| Xbox One | No data | 7.0 |
| Xbox Series X | 96 | 8.0 |

For each run, every stored field was compared with the pre-ingest oracle. Metascore
provenance points to the detail fetch; Userscore points to that detail fetch for the
lead platform and to the matching successful platform URL for each other platform.

Direct external HTTP checks compared `/games/1/` with the oracle, including exact
description hash, URLs, all score pairs and both natural nulls. Chromium additionally
followed `/ → /games/1/ → /`, loaded the real cover and CSS, and checked zero page
errors and no horizontal overflow at 1280 and 390 px. Screenshots:
[desktop](../evidence/imp-02-card-desktop.png), [mobile](../evidence/imp-02-card-mobile.png).
Both summaries correctly remain pending; this is not AI or full `AC-UI-02` acceptance.

## Adversarial finding and correction

Review against the [catalog provenance contract](../design.md#каталог-и-provenance)
found a material counterexample outside the successful live observations: an
existing non-null score survives a later successful response containing `null`,
but `apply_game_dto` moved its provenance to the new response that did not supply
that score. This affected Metascore and lead/non-lead Userscore, including zero.

The new `test_missing_scores_preserve_values_and_their_accepted_source` reproduced
four failing subcases before the correction. The merge now keeps each retained
score's source and still records the new fetch attempt. Newly accepted numeric
values, including zero, update provenance; a naturally absent stored score records
the successful observation of absence. `test_natural_nulls_and_new_zero_scores_have_their_own_source`
guards that boundary. Other valid game fields continue updating during a partial
score response. No migration is needed; historical incorrect references are not
automatically reconstructed.

[Execution excerpts](../evidence/imp-02-revalidation-2026-09-14.txt) contain the failing
reproduction and the subsequent full local `scripts/check.py` result: 263 application
tests, 6 scripts tests, 18 planning tests, 7 AI-integrity tests and 9 selection tests,
Ruff/mypy/Django/migration drift/static build and frozen/candidate verifiers passed
on Python 3.12/PostgreSQL 16. The research environment was used only for the existing
Playwright browser tooling and was not modified. Application DB migrations were
not run locally; tests used the isolated checks database.

## Exit-criterion mapping and review boundaries

| Criterion | Evidence |
|---|---|
| Fixtures and independent field oracle precede parser | Original minimised HTML/SSR and unchanged expected JSON; historical fixture-provenance review; fresh source observation before live DB writes |
| Create/update/alias without duplicates (`AC-DATA-01/02`) | Public before/after snapshots for two real runs; hosted/local identity/alias/conflict/constraint regressions |
| Complete scalar and platform fields (`AC-DATA-03/04`) | Independent source observation → actual VDS DB → direct public card comparison; browser navigation/screenshots |
| Natural null and non-destructive update (`AC-DATA-05/06`) | Actual PS4/Xbox One nulls; frozen corrupted fixture, invalid DTO/score, blank/null merge and retained-score provenance regressions |
| Atomic core/job intent | Existing forced job-creation-failure rollback test, repeated-job test and public stable job IDs |
| Diagnosable provenance | Successful per-request URL/time/hash records, separate per-score source checks, retained-score regression; general game pointer identifies the accepted core update |

Adversarial self-review checked identity collisions, platform identity drift,
partial/invalid scores, null-versus-zero, successful-but-empty responses, rollback,
fake-versus-live evidence and stale build identity. No separate-agent review is
claimed. The HTTP verifier initially compared the whole list-link text to the title;
the link also contains developer/score, so the verifier was corrected to check the
title element and exact target ID. Application UI and the frozen oracle were unchanged.

The first two live runs and screenshots above precede the provenance correction.
Hosted CI and public redeployment/recheck of the corrected candidate are still
required before completing this cycle. No quality oracle, source contract or
acceptance threshold was weakened. Manual candidate state does not prove hourly
scheduling; live source failures, populated restore/concurrency, summaries and later
gates remain their own tasks.
