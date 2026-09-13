# Implementation audit at `07b6b40`

Date: 2026-09-12. Requirements: `SEL-02`, `AI-03`, `NFR-01`–`NFR-06`, `UI-02`.
Current task status belongs only to [action_plan.md](../../action_plan.md).

The owner requested analysis, then authorized corrections. The analysis ran the complete local
`scripts/check.py` successfully (166 application tests), queried the development database read-only,
built `metacritic-audit-checks:07b6b40`, and executed eight temporary PostgreSQL counterexamples.
Those temporary tests ran from stdin and were not committed: the observations below are a dated
audit record, not a reproducible regression suite. Each correction must commit its regression
before claiming closure. No live Metacritic or paid AI calls were made during the audit.

## Container regressions

- `evals/review_selection` is absent from the checks image, although `scripts/check.py` invokes it.
- A cold import of `reviews.selection` in the new image with `--network none` fails while tiktoken
  tries to download `o200k_base.tiktoken`; the vocabulary is not packaged with the dependency.
- `scripts/provision_db.py` requires scheduler/worker credentials that `db_setup` does not receive
  in Compose. The local ignored `.env.app` masks the missing container environment mapping.

These are owned by the [IMP-01 container correction](imp_01_container_correction.md).
The latest hosted success found during the audit was [run 34575308702](https://github.com/ZheleznovAG/metacritic-ai-assignment/actions/runs/34575308702)
at `f299cabb`, nine commits before the audited HEAD. That run does not verify the audited code.

## Application counterexamples requiring separate corrections

| Owner / requirement | Observed counterexample | Relevant implementation |
|---|---|---|
| IMP-03 / SEL-02 | One initial game plus two 24-item browse pages leaves 41 of 49 games after exhaustion; eight page-tail identities are discarded when the cursor advances | [selector](../../app/processing/selector.py) |
| IMP-04 / AI-03 | Three unchanged reviews: first daily job is complete, next is unstable with unique_count=0 and unique_count_mismatch | [collector](../../app/reviews/collector.py) |
| IMP-04 / AC-AI-05 | Editing all three texts while keeping review IDs produces a complete collection but reuses the old corpus and model-input fingerprint | [corpus](../../app/reviews/corpus.py) |
| IMP-04 / NFR-04 | A new pending collection contributes a fourth review to a corpus whose reported_count still comes from the previous three-review terminal job | [corpus](../../app/reviews/corpus.py) |
| IMP-04 / NFR-01–NFR-02 | A crash after terminal page commit but before corpus/job creation leaves complete collection, no corpus, no summary job and no next claim | [collector](../../app/reviews/collector.py) |
| IMP-04 / NFR-04 | Five successful pages followed by the first transport failure immediately fail the collection instead of scheduling a retry | [collector](../../app/reviews/collector.py) |
| IMP-04 / AI-01–AI-02 | A mock model response supporting a claim with absent R99 is marked succeeded while saving zero claims | [summary worker](../../app/summaries/worker.py) |
| IMP-05 / UI-02 | An existing valid summary plus a newer pending collection renders ok rather than the stale state specified in design.md | [summary presentation](../../app/presentation/summaries.py) |

All eight assertions of the intended contracts failed; there were no test execution errors.
The source-size fixtures contain 24 items on the first two browse pages. The summary checks used
fixtures/fake responses and the actual application code on an isolated test database.

## Other boundaries

The local database contained 41 games, 91 platform rows, 182 review jobs (177 pending), 776 reviews
and two successful summaries for Orbitals. Its latest scheduler slot was 2026-09-11 14:00 UTC.
These are snapshots of local probe state, not evidence of continuous public operation.

The application still needs similarity, the full browser E2E, sustained AI/storage capacity,
failure/concurrency hardening and public/release verification. UI sort controls and the IMP-05
public-smoke deferral need review against the implementation-plan exit criterion. Frozen selection
and summary baselines verify their own inputs; they do not establish correctness of corpus
generation or queue throughput. Historical review files remain dated evidence, not current status.
