# UI-OPT-03 local browser measurements

These are dated live observations, excluded from deterministic CI. The ordinary
container suite still runs the fixture pagination, image priority, query budget,
keyboard/no-JS and monitoring recovery regressions. Current status belongs only
to [action_plan.md](../../../action_plan.md).

Run from the repository root after starting the local container app:

```powershell
npm install --prefix .artifacts/ui-opt-03-tools --no-audit --no-fund lighthouse@13.5.0 axe-core@4.13.0
.\.venv-app\Scripts\python.exe research/reviews/20261005_ui_opt_03/audit.py
.\.venv-app\Scripts\python.exe research/reviews/20261005_ui_opt_03/interactions.py
.\.venv-app\Scripts\python.exe research/reviews/20261005_ui_opt_03/image_probe.py
```

Requires Node 24 and the project's pinned Playwright/Chromium installation. Node
packages and full Lighthouse reports remain under ignored `.artifacts/`; no Node
dependency is added to the application. `audit.py --base URL --output DIRECTORY`
supports another local runtime. The interaction/probe scripts use the default
local address/output. `image_probe.py` reads the preceding browser observations
and navigates three original covers and their smaller-size query variants.

The audit checks 18 page/theme/viewport combinations and uses an unnamed-button
negative control to verify axe detects a real defect. Lighthouse performs four
navigation audits with cold browser profiles and default simulated throttling;
desktop viewport is 1280×900, mobile is 390×900 with Lighthouse's mobile DPR.
The event script samples keyboard/select/disclosure interactions above Chromium's
16ms observation threshold; absent entries mean no reported slow sample, not INP=0.

Raw resource and CDN observations vary with the catalog and external network.
The local scripts are measurement tools, not full WCAG conformance or field INP
certification. See [acceptance and review](../../../docs/requirements/ui_opt_03_review.md)
and its independently saved report extracts/source hashes.
