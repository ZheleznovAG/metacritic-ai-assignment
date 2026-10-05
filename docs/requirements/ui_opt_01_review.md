# UI-OPT-01: bounded catalog and responsive foundation

## Scope and traceability

Post-submission correction for UI list/detail navigation and readability (UI-01–UI-05,
AC-UI-06), catalog scalability and monitoring accessibility. Current status belongs to
[action_plan.md](../../action_plan.md).

The catalog uses PostgreSQL filtering, score aggregation and deterministic sorting with an
ID tie breaker. Each response contains at most 30 games. Search/platform/sort/page remain
GET state; detail and similar-game links retain the return context. Offscreen catalog covers
are lazy, dimensions reserve space, and CSS scales their height with width. Mobile facts
and claims stack; tables scroll inside keyboard-accessible regions. Monitoring refresh
recreates the region attributes. Public catalog/detail cache lifetime is 60 seconds;
health and monitoring remain uncached.

## Adversarial review

- A changed sentence capitalisation broke the let's-play warning assertion. The assertion
  now checks the complete warning as rendered; escaping/link/provenance checks remain.
- A 5,000-digit page parameter raised ValueError in detail back-link parsing. Invalid
  integer conversion now falls back to page 1; a regression check exercises both endpoints.
- Intrinsic image height without CSS height:auto could distort resized covers. Corrected.
- Stable ID ordering prevents ambiguous page boundaries for equal scores/titles.
- Platform-specific scores, null scores/dates, invalid/oversized pages and preserved
  filter/pagination URLs have application coverage.
- A repeat suite after starting the local app reached 572 passing application tests but
  failed the existing grant test with DuplicateTable. That test requires an unmigrated
  application database. Verification uses a separate Compose project with compose.ci.yaml;
  README now exposes the repeatable isolated command. No application tables were deleted.

## Verification

Independent outputs: [checks excerpts](../evidence/ui-opt-01/checks.txt),
[source hashes and outcomes](../evidence/ui-opt-01/verification.json), and
[live browser observations](../evidence/ui-opt-01/browser.json).

| Exit criterion | Evidence |
|---|---|
| Canonical build and complete checks | Build exit 0; isolated suite exit 0, 572 application tests, 22 script tests and all offline checks |
| Real pagination and preserved return state | `CatalogPaginationJourneyTests`: 61 games, pages 30/30/1, 1280/390/320px, JS/no-JS; application checks above |
| Live UI and no page overflow | 18 browser journeys, filters/sort/reload/empty; browser observations above |
| Responsive visual review | [Desktop catalog](../evidence/ui-opt-01/catalog-desktop.png), [390px detail](../evidence/ui-opt-01/detail-390.png), [320px monitoring](../evidence/ui-opt-01/monitoring-320.png); additional screenshots stay in `.artifacts/ui-opt-01-browser/` |
| Keyboard and history | Tab through filter controls, Enter card/back, visible focus, browser back/forward URL state: PASS |
| HTTP/static/security smoke | `smoke.py http://127.0.0.1:18081 --version local`: 8/8 |

Accepted boundaries: local catalog grows under its scheduler, so oversized page requests clamp
to the available last page. Synthetic pagination covers actual page 3 independently. Monitoring
history wraps heavily on 320px; presentation improvement belongs to UI-OPT-02. Public cache
permits up to 60 seconds of staleness. Live provider quality, hosted CI and public deployment
are outside this correction's acceptance; historical G-gates are unchanged.
