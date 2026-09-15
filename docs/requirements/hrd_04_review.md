# HRD-04: AI failure isolation and quality regression

Task `HRD-04`. Requirements/risks per `implementation_plan.md#hrd-04`:
timeout, malformed output, quota exhaustion and prompt injection isolated
from batch/UI, with the previous valid summary preserved; capacity
scenarios, selected-input/cache/version checks and the frozen quality eval
of the final contour repeated; dataset/oracle never adjusted to fit output.
Current task/gate status belongs only to [action_plan.md](../../action_plan.md).

## Scope of this cycle

Auditing the existing suite against each clause of `HRD-04`'s exit
criterion found four of six already covered, continuously, by prior
IMP-04/HRD-02 work and CI:

| Clause | Existing coverage |
|---|---|
| Malformed output isolated | `test_summaries_contour.py::ValidateOutputTests`, `test_summary_validation.py` (grounding, unknown-support rejection, list-status handling), `test_summaries_worker.py::MalformedOutputTests` |
| Quota exhaustion isolated | `test_summaries_worker.py::QuotaExhaustionTests`/`RateLimitedTests`, `test_summary_admission.py::ConcurrentQuotaTests`, live-verified in `IMP-07` |
| Previous valid summary preserved | `presentation/summaries.py`'s stale-fallback design, exhaustively covered by `test_summary_freshness.py` (11 tests: pending/failed/unstable collection, cache reuse across identical corpora, contour-change invalidation, equal-timestamp tie-breaks) |
| Capacity scenarios / selected-input / cache / version checks repeated | `test_summary_admission.py`, `test_summaries_worker.py`'s cold/unchanged/changed-input classes, all run on every `scripts/check.py` |
| Frozen quality eval of the final contour | `evals/reviews/score_run.py --verify` (in `scripts/check.py`) confirms `evals/reviews/baseline/run.json`'s `prompt_version`/`output_schema_version` (`3.0.0`/`2.1.0`) exactly match `summaries/contour.py`'s current `PROMPT_VERSION`/`SCHEMA_VERSION` — the frozen `SPK-05` live-model run already targets the shipped, final contour, not an earlier draft |

The two gaps, both with zero existing coverage before this cycle:

- **Timeout isolated from batch.** No test anywhere exercised a real
  transport-level failure (timeout, connection error) reaching
  `summaries.worker.process_job`. `groq_adapter._post`'s
  `except httpx.HTTPError` (which subsumes `httpx.TimeoutException`) was
  read and traced, but never actually driven by a raised exception in a
  `MockTransport` handler — every existing test only ever returns an
  `httpx.Response` (even the "failure" ones, via non-2xx status codes).
- **Prompt injection isolated.** `prompt_3_0_0.md` explicitly instructs the
  model to treat review text as untrusted data, never instructions — a
  live-model behavioral property already measured once by the frozen
  `SPK-05` eval (see the "frozen quality eval" row above) and not
  re-measurable deterministically without a real model call. What *is*
  deterministically provable, and had zero coverage: that untrusted review
  text can never structurally escape its own JSON string value in the
  request payload to alter the actual message roles sent to the provider,
  regardless of its content.

## Fix

No production code changed. Four new tests:

- `test_summaries_worker.py::TransportFailureTests`:
  - `test_a_network_timeout_is_retryable_and_records_no_summary` — a
    `MockTransport` handler raising `httpx.ReadTimeout` mid-call; asserts
    the job becomes `retryable`/`transport_error`, the attempt is recorded
    with a matching outcome, and no `ReviewSummary` is created.
  - `test_one_jobs_timeout_does_not_corrupt_an_independent_jobs_own_claim`
    — after job A's `httpx.ConnectTimeout`, asserts `claim_next_job` still
    correctly finds the independent, still-pending job B (not locked,
    corrupted, or lost). Job B's own attempt then correctly lands on
    `delayed_capacity`/`quota_exhausted` — this is the shared per-credential
    quota ledger (`quota.py`'s `_blocks()`) conservatively pausing a full
    minute after *any* attempt (success or failure alike) whose response
    carried no rate-limit headers, already covered separately by
    `WorkerFairnessTests`, not job A's failure corrupting job B.
- `test_summaries_contour.py::PromptInjectionIsolationTests`:
  - `test_the_system_message_is_the_trusted_prompt_verbatim_unaffected_by_review_content`
    — an adversarial review (embedded fake `"role": "system"`/`"role":
    "user"` JSON fragments, escaped quotes, control characters including
    `\x00` and ` `) as input; asserts the system message is byte-for-byte
    `contour.load_system_prompt()` and exactly two messages exist.
  - `test_adversarial_review_text_round_trips_intact_inside_its_own_json_string`
    — the same adversarial review; asserts the user message, JSON-decoded,
    contains exactly one review with the *exact* original adversarial
    string as its `text` — proof the text never escaped its string value to
    add a fabricated review or alter the structure.

## Verification that the tests carry real signal

Before committing, `groq_adapter.py`'s `except httpx.HTTPError` was
temporarily narrowed to `except httpx.RemoteProtocolError` (which does not
subsume `httpx.ConnectTimeout`/`httpx.ReadTimeout`): both new
`TransportFailureTests` failed with an unhandled exception, confirming they
exercise the real handling path. Separately, `contour.build_request_payload`
was temporarily rewritten to naively f-string-concatenate the user message
instead of using `canonical_json` (the exact vulnerability class this cycle
guards against): `test_adversarial_review_text_round_trips_intact_inside_its_own_json_string`
failed with `json.decoder.JSONDecodeError: Extra data`, confirming it
catches a real structural break. Both were restored with no diff against
the original files (`git diff` empty for `summaries/groq_adapter.py` and
`summaries/contour.py`).

## Verification

321 application tests (4 added) and the full `scripts/check.py` suite
(ruff format/lint, strict mypy, migration drift, static build, all offline
evals/verifiers) pass green locally. This closes `HRD-04`: combined with
the pre-existing malformed-output/quota/freshness/capacity/frozen-eval
coverage above, all clauses of the exit criterion now have evidence;
`HRD-04` moves to `Verified`.
