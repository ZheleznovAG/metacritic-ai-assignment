# UI-OPT-02: visual hierarchy and readable observations

## Scope and acceptance

Post-submission presentation work for UI-01–UI-05 / AC-UI-01–06, SIM-01 /
AC-SIM-03, OPS-01, YTP-03 and R-SEC-01. Status belongs only to
[action_plan.md](../../action_plan.md). Ranking, provider policies and work ownership
remain the accepted contracts in [design](../design.md).

| Area | Exit criterion | Verification |
|---|---|---|
| Catalog | Cover/title/score/developer/date/platform hierarchy, labelled scores, removable filters and page position | Template integration, 30-game query budget, live browser/screenshots |
| GET state | Filter removal preserves other filters/sort, resets page; reload/history/back/no-JS work | Escaping/removal tests and pagination/browser journeys |
| Hero | Saved maximum Metascore/User score explicitly labelled across platforms; zero/null distinct; missing cover tolerable | Integration boundary tests, desktop/390/320px screenshots |
| AI summaries | Mobile stacked claims, honest empty states, compact selected-count/time, native closed provenance with model/counts/UTC/prompt/fingerprint | Existing freshness/escaping checks and browser disclosure |
| Similar games | Compact lazy cover cards and saved Metascore; matching explanations retained; no numeric claim of confidence | Existing two-SELECT/no-ranking contract, navigation and new media test |
| Let's Play | Experimental marker and limitation visible in every state | Template integration/browser |
| Monitoring | Working/Waiting/Stale/Stopped/Unknown labels preserve raw state; relative times retain UTC; readable scroll table; region attributes survive refresh | Timestamp boundary checks, existing recovery browser test and 320px visual review |
| Accessibility | Keyboard/focus, reduced-motion support, readable light/dark badges, no page overflow at 320/390 | Browser measurements/screenshots and keyboard flow |
| Regression | Complete canonical build/suite and smoke | Isolated Compose checks and live HTTP/static smoke |

One batch query reads platform labels only for page members. Similar media/score fields are
added to its existing second SELECT. Hero scores aggregate already loaded platform DTOs.
Provenance reads saved attempt/job identity, never substitutes current prompt versions for an
older summary. Observation formatting never changes scheduler state or connection freshness.

## Adversarial review

- Hero maxima can come from different platforms. The explicit "Highest saved scores across
  platforms" caption and the original platform table prevent implying a single platform's pair.
  Zero is checked separately from missing values.
- Platform labels must not bring back N+1 or full-catalog hydration: the independent query
  test executes exactly 3 SELECT for both 1 and 61 games. Similar cards retain their two-SELECT
  no-HTTP/model/ranking check.
- Removable filters are ordinary GET links, preserving the other filter/sort and resetting
  pagination. A hostile search string is escaped in the chip and encoded in links.
- Summary provenance includes the saved attempt's prompt version and job's fingerprint, not
  current configuration. It is available for stale/insufficient results too. Empty claims have
  explicit wording; pending/unavailable reasons and the existing freshness contract remain.
- Observation labels do not certify overall health. Missing/invalid/future timestamps have
  explicit labels; UTC survives in datetime/title. A timestamp assertion uses one DOM read
  to avoid a race with polling. Recovery tests still check committed status and stale snapshots.
- Existing developer assertions were updated to check its new hero location; unknown
  developer remains explicit. An initial new-test mypy failure was corrected with a presence
  assertion. Final checks below supersede those failed candidates.
- The initial screenshot pass ran before covers loaded. The final pass waits for completion
  and independently records first-four cover observations: all four loaded in all 12 cases.

## Independent verification

[Checks excerpts](../evidence/ui-opt-02/checks.txt),
[source hashes / Docker identity / outcomes](../evidence/ui-opt-02/verification.json), and
[live browser observations](../evidence/ui-opt-02/browser.json) record the executed candidate.

| Exit criteria | Independent artifact |
|---|---|
| Catalog hierarchy and filter UX | [Desktop](../evidence/ui-opt-02/catalog-desktop.png), [390px focused catalog](../evidence/ui-opt-02/catalog-390.png), integration filter/escaping/query checks |
| GET state, pagination, keyboard/no-JS | 12 live combinations: reload, filter removal, Enter card/back, back/forward; existing 61-game pagination journey in the complete suite |
| Hero and missing scores/media | Zero-score/template checks, [dark 390px detail](../evidence/ui-opt-02/detail-dark-390.png), [fixture 320px](../evidence/ui-opt-02/fixture-detail-320.png) |
| Summaries/provenance/Similar Games | [Ready fixture](../evidence/ui-opt-02/fixture-summary-similar.png); mandatory processing-to-browser journey checks audience separation, counts, native disclosure by keyboard, saved similar navigation and 320px overflow |
| Experimental marker | Template integration and all live detail combinations |
| Monitoring and UTC/ARIA | Existing committed-state/reconnect/older-snapshot tests, all live JS/no-JS combinations, [320px monitoring](../evidence/ui-opt-02/monitoring-320.png) |
| Light/dark and reduced motion | Minimum measured badge contrast 8.31:1; reduced-motion transition disabled; visible focus and no page overflow in all 12 cases |
| Canonical regression/deployment | Build exit 0; isolated suite exit 0: 578 application + 22 scripts tests, all offline checks. Local app healthy; smoke 8/8; running web image equals built runtime ID |

Accepted limits: live summaries await provider work and live similar rows were absent;
ready results are covered independently by the frozen fixture. No full accessibility or
performance audit is claimed: UI-OPT-03 owns measurements beyond the checks above. All
additional screenshots and raw local logs remain under `.artifacts/`. Historical gates,
hosted CI and public deployment acceptance are unchanged.
