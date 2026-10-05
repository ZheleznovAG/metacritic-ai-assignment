# UI-OPT-03: performance and accessibility acceptance

## Frozen measurement contract

Post-submission UI-01–UI-05 / AC-UI-01–06, OPS-01 and R-SEC-01 work.
Current status belongs to [action_plan.md](../../action_plan.md).
Measure the existing catalog and one saved detail at desktop 1280px and mobile
390px before changing presentation. Lighthouse 13.5.0 and axe-core 4.13.0 run
against the local container app; live covers are external, not CI fixtures.

- Catalog: at most 30 cards, fewer than 800 DOM elements; exactly three catalog
  SELECTs for one and 61 games, including the batched platform labels.
- Images: explicit intrinsic dimensions, async decoding, reserved aspect ratio;
  prioritize only measured LCP candidates; later covers are lazy. The initial
  first-cover-only hypothesis is explicitly reviewed against measured LCP below.
- Local lab targets: CLS <= 0.1 and TBT <= 200ms. Record LCP, transferred bytes,
  requests and performance/best-practices scores without hiding external failures.
  LCP > 2.5s requires investigation, not a fabricated field-performance claim.
- Accessibility: no serious/critical axe violations in light/dark catalog/detail
  and monitoring at 320/390/1280px; record Lighthouse accessibility results.
  Keyboard/no-JS/reduced-motion journeys remain the independent UI-OPT-02 checks.
- Cache: public catalog/detail max-age=60; monitoring/health never cached.
- Full canonical container build/suite, live smoke and saved independent evidence.

Lighthouse does not establish field INP. Record that limitation and observe local
interaction events separately; a lab sample does not certify production users.
Do not add a proxy or conditional-cache machinery unless measurements justify it.

## Findings and executed verification

### Adversarial review and corrections

- The baseline axe audit found a light-theme nested `.no-data` label at 3.39:1
  and disabled pagination at 2.63:1 (light) / 4.07:1 (dark). Removing the parent
  opacity and using the existing opaque muted palette fixes both. The baseline
  nodes and calculated ratios are independently saved, rather than inferred from CSS.
- The first-cover-only candidate made the second visible mobile cover lazy. Its
  measured LCP was 2.90s, and Lighthouse identified that image as the LCP node.
  The final two-cover priority represents the first mobile row; the remaining
  covers stay lazy. This revises the initial hypothesis using the measured node,
  without changing the performance thresholds. The intermediate report is retained.
- The missing favicon caused a real 404 console error. A local SVG favicon now
  serves through the existing immutable static pipeline on all four HTML pages.
- Review of axe's `incomplete` records found that the hero score div's aria-label
  lacked a naming role. Adding `role="group"` makes that label available to
  assistive technology. The remaining mobile contrast records refer to clipped
  table columns (and single-character cells); the same unclipped tables pass the
  desktop audit. Table region focus/scroll behavior remains covered by browser tests.
- Smaller CDN query variants were tested for three original covers: original 200,
  changed dimensions 403 in all three pairs. Do not manufacture `srcset` variants
  or silently break images. Their response sizes/types/hashes are saved.
- Short public max-age=60 and monitoring no-store are independently observed.
  Local response latency does not justify adding ETag/database invalidation work.
- Audit injection adds an unnamed button and independently detects `button-name`;
  the negative-control node is removed before normal results are recorded.
- Catalog SQL remains three SELECTs for one and 61 games, with one batched platform
  read. The full suite checks pagination across 61 games and browser widths/no-JS;
  the live page has 30 cards and 329 DOM elements at every measured width.

### Independent evidence

The [source hashes and image identities](../evidence/ui-opt-03/verification.json)
bind this candidate to the built/runtime image. [Checks and smoke excerpts](../evidence/ui-opt-03/checks.txt)
record the final suite: 578 application tests, 22 script tests, all offline checks,
build/suite exit 0 and smoke 8/8. The suite includes the mandatory processing-to-browser
journey, query budgets, architecture, database-role boundaries and monitoring recovery.
An independent no-network image probe confirms application source bytes in both
runtime and checks equal the host source hashes; generated `staticfiles` are excluded
from that source comparison. Static delivery and the running image identity pass smoke.

| Final local navigation audit | Performance | Accessibility | Best practices | LCP | CLS | TBT | Transfer | Requests |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Desktop catalog | 89 | 100 | 77 | 2.22s | 0 | 0ms | 3,373,410 B | 23 |
| Desktop detail | 100 | 100 | 77 | 0.22s | 0 | 0ms | 70,039 B | 5 |
| Mobile catalog | 98 | 100 | 77 | 1.82s | 0 | 140ms | 1,478,950 B | 11 |
| Mobile detail | 98 | 100 | 77 | 1.67s | 0 | 125ms | 41,239 B | 4 |

[Lighthouse extracts](../evidence/ui-opt-03/lighthouse.json) preserve baseline,
intermediate, concurrent-load and final reports, timestamps, browser identity, report hashes,
metric values, network records and relevant audit details. These are single local
lab runs, not a distribution or proof that the priority change alone caused the
observed score difference. Transfer remains essentially unchanged.

One final-source audit overlapped the CPU/browser work of the container suite and
reported mobile catalog TBT 205ms. That report is retained as `contended-final-source`.
The final measurements were repeated after the suite exited, without concurrent
test work. Host contention is a plausible explanation, not a proven causal claim;
these observations reinforce the limits of individual local lab scores.

[Browser observations](../evidence/ui-opt-03/browser.json) record 18 combinations:
catalog/detail/monitoring × light/dark × 1280/390/320px. No axe violations or page
overflow were reported. [Baseline contrast findings](../evidence/ui-opt-03/contrast-baseline.json),
[negative control](../evidence/ui-opt-03/negative-control.json) and
[CDN counterexamples](../evidence/ui-opt-03/image-probe.json) independently support
the changes and the remaining image limitation. Images retain async decoding,
reserved 3:4 ratio and intrinsic sizes checked by the application regressions.

[Interaction samples](../evidence/ui-opt-03/interactions.json) report native
keyboard/select/focus events at 24–32ms, above Chromium's 16ms observation threshold.
They do not establish field INP. Navigation Lighthouse reports TBT;
[Chrome's metric guidance](https://developer.chrome.com/docs/lighthouse/performance/lighthouse-total-blocking-time)
describes that lab metric. No production-user telemetry was collected.

Visual review inspected the [390px catalog](../evidence/ui-opt-03/catalog-390.png)
and [390px detail](../evidence/ui-opt-03/detail-390.png). The
[desktop catalog](../evidence/ui-opt-03/catalog-1280.png) and
[desktop detail](../evidence/ui-opt-03/detail-1280.png) are also saved.
The independent prior [UI-OPT-02 journey](ui_opt_02_review.md) covers ready summaries,
Similar Games, disclosure, reduced motion and keyboard/no-JS transitions; the live
detail screenshot has pending summaries and a saved similar entry with missing
cover/score. Ready summaries and image-rich neighbor states are not represented
by this live axe sample.

### Accepted measurement limits

External covers still dominate catalog transfer (~3.22MiB desktop / 1.41MiB mobile).
The CDN sets `__cf_bm`; third-party cookie/DevTools cookie findings account for the
remaining best-practices score. Original images remain usable, changed resize
queries do not. A controlled image cache/proxy is separate work, not a speculative
URL rewrite in this acceptance cycle. No bandwidth-reduction claim is made.

At 390px the two eager covers form the visible row. At 320px the layout has one
column, so the fixed SSR policy can eagerly request one extra cover. This bounded
tradeoff preserves no-JS behavior; the remaining page covers are lazy.

Automated accessibility and these visual/keyboard samples do not certify full
WCAG conformance. External network timing/catalog contents can change. Hosted CI,
public deployment and field INP are not asserted by this local evidence. Reproduction
commands are in the [dated audit notes](../../research/reviews/20261005_ui_opt_03/README.md).
