# Project snapshot — 2026-10-05

This is a dated description of code and evidence, not a task/gate tracker.
[action_plan.md](action_plan.md) owns all acceptance decisions and dependencies.
Source baseline: FIN-ARCH `3270226`; FIN-DOCS changes documentation only.

## Current application

Django on Python 3.12 and PostgreSQL 16, packaged with Docker Compose. Three
long-running application processes: web, hourly scheduler and enrichment worker.
PostgreSQL owns catalog data, immutable review snapshots/corpora, provider attempts,
leases, queues and monitoring observations. No Redis, Celery or separate vector DB.
[Design](docs/design.md) defines contracts; [FIN-ARCH evidence](docs/requirements/fin_arch_review.md)
records the worker composition root and remaining dependency cycles.

The catalog supports title search, platform filters, score/release-date sorting and
30-item pagination. Cards show stored metadata, separate critic/user summaries,
provenance and up to five precomputed similar games. Navigation retains list context.
Desktop/mobile UI and monitoring have deterministic browser coverage; the UI changes
and architecture refactor are local revisions, not a newly verified public release.

Monitoring `/ops/` and `/ops/status/` is public and read-only. `/ops/login/`, logout
and authorized `POST /ops/run/` use Django auth, CSRF, durable admission and the same
processing lease as scheduled work. Web has SELECT plus explicit narrow grants for
sessions, manual requests, admission, login throttling and one user column. No
self-registration or Django admin UI. [Operator contract](docs/bonus2_design.md).

## Runtime policies in source

| Component | Identity/version | Evidence and limits |
|---|---|---|
| Review selection | `1.2.0-meaningful` | [Frozen selection oracles](evals/review_selection/README.md); substantive eligibility and score diversity, not a guarantee of opinion representativeness |
| Review summary | `openai/gpt-oss-20b`; prompt `3.0.0`, schema `2.1.0` | [Contour source](app/summaries/contour.py), [baseline evaluation](evals/reviews/baseline/scorecard.json) |
| Similarity | `text-hybrid` `3.0.0` | [ADR-0003](docs/decisions/0003-text-hybrid-similarity.md), [ADR-0004](docs/decisions/0004-foreign-description-gate.md); saved embeddings/TF-IDF, foreign-description gate, precomputed neighbors |
| Let's Play selection | `letsplay-select` `1.0.0` | [Frozen metric](evals/letsplays/metric.md); experimental, post-submission |
| Let's Play conclusion | `openai/gpt-oss-120b`; prompt/validation `2.1.0`, schema `2.0.0` | [ADR-0006](docs/decisions/0006-letsplay-conclusion-accepted-with-limitation.md); experimental, acceptance includes an explicitly unmet quality criterion |

These are active source versions, not a fresh inspection of a remote container.
The old `genre-jaccard` `1.0.0` remains frozen comparison tooling; it is superseded
for runtime by text-hybrid. Its decision was historically numbered ADR-0002 and is
now [ADR-0007](docs/decisions/0007-genre-similarity-policy.md), resolving the duplicate
with the Bonus 2 scope ADR-0002. Frozen policy/report hashes are unchanged.

## Independent evidence and remaining limits

- FIN-ARCH container verification: 586 Django/application tests and 22 deployment
  script tests, offline evaluators, browser journey, migration drift and permission
  boundaries passed; local HTTP/CSS smoke passed 8/8.
  [Verification artifacts](docs/evidence/fin-arch/verification.json).
- [UI-OPT-03 evidence](docs/requirements/ui_opt_03_review.md) records local Lighthouse
  and accessibility/browser checks. These are lab measurements, not field INP or
  comprehensive WCAG certification. External cover resizing returned 403; cover
  byte volume remains a limitation, although initial loading is bounded.
- Similarity's 24-query second set was registered before tuning; its reported
  nDCG@5 is evaluation evidence, not an independent deployment holdout or proof of
  generalization. [Protocol and results](evals/similarity/text_comparison_v2.md).
- Source descriptions can belong to another game; Metacritic identities/counts can
  change. Bounded retries and identity checks preserve integrity, not source truth.
- YouTube captions/IP blocking and search quotas constrain Let's Play throughput.
  The recorded estimate is approximately 40–50 games/day before IP blocking, not a
  guaranteed SLA. Conclusion quality limitations and provider-unit budgets remain
  explicit in [ADR-0006](docs/decisions/0006-letsplay-conclusion-accepted-with-limitation.md) and the metric.
- Remaining package cycles and legacy frozen-policy dependency are documented in
  FIN-ARCH. [Risk register](docs/risks.md) preserves risk IDs and residual context.

## Original submission versus later development

The original take-home selected Bonus 2, submitted release `6ade911`, and excluded
Bonus 1. Delivery was rejected for lateness; later work does not change that outcome.
Original G4/G5/G6 decisions and their evidence are historical. The subsequent audit
requested reacceptance; closing corrections does not silently replace the owner's
gate decision. The authoritative record remains action_plan.md.

Post-submission work added text similarity, review-selection corrections, metadata,
experimental Let's Plays and the UI/architecture revisions. [ADR-0005](docs/decisions/0005-bonus1-after-submission.md)
amends running-service scope while preserving the submitted scope. Original audits,
incidents and deployment observations remain in [history](docs/history/operations.md)
and the [requirement/evidence index](docs/evidence.md).

## Deployment and repository observations

The repository is public: [GitHub repository](https://github.com/ZheleznovAG/metacritic-ai-assignment).
[GitHub API observation](docs/evidence/fin-docs/repository.json) records the actual
visibility check; historical private/invite records describe the submission period.
Secrets, private deployment configuration, raw transcripts and database exports stay
outside Git.

The original VDS was deleted on 2026-09-21; its former hostname is historical.
A new host deployment is recorded on 2026-09-30. The last recorded public source
revision is `5658162`, with [hosted CI 37108527777](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/37108527777).
FIN-DOCS does not check current remote availability or supply an unverified new URL.
Local preview: [http://127.0.0.1:18081](http://127.0.0.1:18081).

Local/CI preview uses HTTP; production uses an immutable versioned image, internal
PostgreSQL, backups, explicit image identity and separately configured trusted TLS.
[Deployment runbook](deploy/README.md) and [relocation procedure](deploy/relocation_runbook.md)
describe the process. New local checks do not prove hosted CI, deployment or release.
