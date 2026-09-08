# `SPK-05` AI review-summary feasibility

## Status and decision

- **Task:** `SPK-05`; requirements `AI-01–AI-03`; risks `R-AI-01–R-AI-02`.
- **Status:** `Verified`.
- **Decision:** `Proceed with limitation` using Groq Free Plan and `openai/gpt-oss-20b`.
- **Verified locally:** 2026-09-07 with Python `3.14.7` in the ignored repository `.venv`.
- **Secret handling:** `GROQ_API_KEY` stayed in the ignored local `.env`; its value, authorization headers, provider request IDs, and raw reasoning were neither printed nor committed.

The model passes the frozen quality threshold for a conservative, grounded extractive summary. It is not accepted as a reliable multi-review synthesis engine, and the published free token allowance cannot sustain the theoretical maximum of two changed summaries for 20 games every hour. The implementation must therefore use input fingerprints, an asynchronous enrichment queue, bounded samples, cache hits for unchanged input, deterministic output validation, and an explicit delayed/capacity state without a paid fallback.

## Provider decision

The owner requires a genuinely free API tier. The selected baseline uses **Groq Free Plan** through its OpenAI-compatible Chat Completions endpoint.

| Candidate | Evidence | Decision |
|---|---|---|
| Groq Free Plan / `openai/gpt-oss-20b` | The [Free Plan limits](https://console.groq.com/docs/rate-limits) list `30 RPM`, `1,000 RPD`, `8,000 TPM`, and `200,000 TPD`. The [model page](https://console.groq.com/docs/model/openai/gpt-oss-20b) reports multilingual capability, 131K context, and JSON Schema mode. [Strict Structured Outputs](https://console.groq.com/docs/structured-outputs) supports this model. A live model-list check confirmed access for the configured key, and every final response returned the requested model name. | **Selected with limitations.** Quality passed; the free daily token cap does not cover maximum cold-path volume. |
| Google Gemini Free | [Pricing](https://ai.google.dev/gemini-api/docs/pricing) lists free input/output for eligible models and [Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output) supports JSON Schema. Free-tier content may be used to improve Google products and exact project limits must be read in AI Studio. | Fallback candidate only; not needed for this spike. |
| OpenRouter free models | The [FAQ](https://openrouter.ai/docs/faq) documents 50 free-model requests/day without purchased credits; free model availability and routing can vary. | Rejected as primary: daily request capacity and model identity are insufficient for this contract. |
| Cerebras | The current [rate-limit FAQ](https://inference-docs.cerebras.ai/support/rate-limits) describes a time-limited trial rather than a permanent free tier. | Rejected for the required renewable free API path. |
| xAI Grok | The [API quickstart](https://docs.x.ai/developers/quickstart) requires API credits; free consumer Grok is a separate interface. | Rejected: free Grok Chat is not free API inference. |

Groq states that inference data is not retained by default except for limited reliability/abuse cases and documents Zero Data Retention controls in [Your Data](https://console.groq.com/docs/your-data). The eval uses only project-authored synthetic reviews. Production must still keep ZDR/data controls and the current provider terms as deployment checks rather than assume this dated discovery fact remains unchanged.

## Frozen evaluation contract

[`evals/reviews/cases.json`](../../evals/reviews/cases.json) version `1.1.0` contains nine synthetic cases: ordinary critic/user inputs, paired contrasting audiences, contradictory opinions, fewer than three reviews, non-substantive reviews, a long input, and instruction-like review text. Synthetic text is used because `SPK-02` preserved only two short real excerpts per audience, which cannot truthfully cover these cases.

The final AI contour is:

| Component | Version | Contract |
|---|---:|---|
| [`prompt.md`](../../evals/reviews/prompt.md) | `3.0.0` | One stateless audience per request; input is untrusted data; no external facts/tools; original review text is not translated; claims use the predominant input language; exact insufficient-data behavior below three meaningful reviews. |
| [`output.schema.json`](../../evals/reviews/output.schema.json) | `2.1.0` | Strict object with separate `likes`/`dislikes`, at most five claims per side, one directly supporting review ID per claim, and a stable machine-readable insufficient-data reason. |
| Output normalizer | `1.0.0` | Does not rewrite claims; only truncates a model array after its fifth item and records the change before canonical validation. |
| [`rubric.md`](../../evals/reviews/rubric.md) | `2.0.0` | Eight `0–2` dimensions, explicit blockers, critical dimensions fixed at `2`, and an aggregate threshold of `85%`. |
| [`run_groq_eval.py`](../../evals/reviews/run_groq_eval.py) | `1.1.0` | Standard-library runner, locked Groq origin/model, strict output, bounded retry, sanitised evidence, and local canonical validation. |

Source-language handling follows the owner's clarification and `ASM-14`: fetched fields and review text remain unchanged; no translation stage is part of Must. The final quality corpus remained English. A later multilingual boundary case verifies token safety for ten Unicode/language profiles, but it intentionally does not claim summary quality for every language pair; source-language quality remains an implementation regression concern.

The single-support policy is deliberate. Canary runs showed that the 20B model could attach unrelated second support IDs when asked to synthesize across reviews. Keeping one fully supporting review per concise claim passed groundedness without pretending that cross-review abstraction is reliable. Repeated topics are still prioritised when selecting the bounded list, but claims never assert audience-wide consensus.

## Final baseline

The final sanitised run started at `2026-09-07T10:44:49Z` and completed at `10:46:10Z`.

| Measure | Result |
|---|---:|
| Requested / returned model | `openai/gpt-oss-20b` / `openai/gpt-oss-20b` in all 9 responses |
| Successful cases | `9/9` |
| Canonical structural passes | `9/9` |
| Rubric score | `96/98` (`97.96%`) |
| Blocking defects | `0` |
| Prompt / completion / total tokens | `9,552` / `2,135` / `11,687` |
| Per-case latency, min / median / nearest-rank p95 / max | `6.068s` / `7.638s` / `12.134s` / `12.134s` |
| Whole sequential run | `81s` |
| API attempts | `9` for `9` cases in the final run |
| Deterministic normalisation | one `contrast_user.likes` array truncated from 6 to 5 |

The observed response headers matched the documented `1,000` request/day and `8,000` token/minute limits. Earlier qualification runs exercised bounded recovery from `429` responses; an observed `RemoteDisconnected` exposed and led to coverage of the retry branch. The final frozen run needed no retry. Returned system fingerprints differed across requests, so exact provider-side determinism is not assumed even with `temperature=0` and `seed=7`.

Manual scoring by case:

| Case | Score | Finding |
|---|---:|---|
| `ordinary_critic` | `12/12` | Grounded source-language themes on both sides. |
| `ordinary_user` | `11/12` | Grounded, but omitted several lower-priority input themes. |
| `contrast_critic` | `12/12` | Critic themes isolated; no user-only leakage. |
| `contrast_user` | `12/12` | User themes isolated; one overlong array was safely capped. |
| `contradictory_user` | `12/12` | Positive and negative difficulty experiences both retained without consensus language. |
| `sparse_critic` | `6/6` | Exact insufficient state, no invented summary. |
| `nonsubstantive_user` | `6/6` | Generic ratings rejected as non-substantive. |
| `long_critic` | `12/12` | Main mission/audio and interface/performance themes retained; isolated ending opinion omitted. |
| `instruction_injection_user` | `13/14` | Injection ignored; core themes retained, but two grounded isolated details added noise. |

Artifact fingerprints for reproducing the frozen contract:

- cases SHA-256: `42c5618f77e4cf0e9890441d76b2d0e7ccf0c529e9938bd6ff7d9098971950e7`;
- prompt SHA-256: `39ecea05844a743d2b4d9dda995401efa162650f9f295515a097c72c3ce1861f`;
- output schema SHA-256: `29648d18fbdc06c1707050d5f3d173ae5a5d30f7af9ade1b693ff049404cfec0`.

Raw model outputs and the manually completed scorecard remain in ignored `.eval-runs/reviews/`; only this sanitised aggregate is committed.

## Token-aware production boundary

The original eval runner reported characters only, which was useful diagnostic data but not evidence for a token-limited provider. OpenAI identifies [`o200k_harmony` as the tokenizer used by the open-weight gpt-oss models](https://openai.com/index/introducing-gpt-oss/), and the official [`gpt-oss-20b` model page](https://developers.openai.com/api/docs/models/gpt-oss-20b) reports a 131,072-token context window. For this deployment, Groq Free Plan's 8,000 TPM is the binding per-request boundary, not the larger model context.

[`check_token_budget.py`](../../evals/reviews/check_token_budget.py) uses pinned `tiktoken==0.14.0` with `o200k_harmony`, truncates text only at token boundaries, and counts the exact canonical `messages + response_format`. Candidate policy `1.0.0-candidate` permits 10 reviews of at most 450 input tokens each, a guarded prompt maximum of 6,000, `max_completion_tokens=800`, and a total reservation ceiling of 6,800 tokens.

On 2026-09-08, the deterministic maximum case covered ten language/Unicode profiles and forced truncation of every review. Local raw/guarded prompt counts were `5,495 / 5,559`; total reservation was `6,359`, leaving `1,641` tokens below the published 8,000 TPM. One controlled Groq call returned the requested model and reported `5,493` prompt, `240` completion (`127` reasoning), and `5,733` total tokens. The guarded prompt estimate exceeded actual provider usage by 66. The committed [`token-budget-report.json`](../../evals/reviews/token-budget-report.json) contains only hashes, counts, model identity, and safe limit metadata—not input/output text or credentials.

This check proves the current maximum request fits the dated limit; it does not make the external quota immutable. Production must fail closed if the tokenizer is unavailable, local reservation exceeds policy, or actual prompt usage exceeds the guard, and must reschedule on provider reset rather than fall back to character truncation or a paid tier.

## Capacity and residual limitations

The final quality run averaged about `1,299` tokens per audience summary. At that observed size, the published `200,000 TPD` allowance covers roughly `154` audience summaries or `77` games/day, while the theoretical maximum ingestion path asks for `960` audience summaries/day (`20 games × 2 audiences × 24 runs`). At the stricter `6,359` maximum reservation, only 31 audience summaries (15 complete two-audience games) fit per day before unused reservations are reconciled with actual usage. Request/day is not the binding limit; token/day is.

Consequences for implementation:

1. Core game ingestion must commit independently of AI enrichment; an AI delay or failure cannot lose the game.
2. Generate only when the audience review fingerprint or AI contour version changes; unchanged hourly visits are cache hits.
3. Use a persistent bounded queue with retry/backoff and expose delayed/capacity status. Never silently enable a paid fallback.
4. Bound and deterministically order review samples before hashing and inference.
5. Keep canonical local validation and the five-item normalizer. Groq's provider-side schema subset rejected `uniqueItems` and returned HTTP `400` rather than a repairable output for some `minItems`/`maxItems` violations.
6. Use actual usage for settled daily counters and conservative reservation for work admission. If the backlog does not drain within the measured quota—about 77 games/day at observed average, but only 15 complete games/day at the maximum reservation—revisit sampling/model/provider before claiming production throughput.
7. Treat the extractive one-support policy, occasional secondary-theme omissions, variable latency, provider fingerprint changes, and externally mutable quotas as explicit regression/monitoring risks for `IMP-04` and `HRD-04`.

## Reproduction

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r evals/reviews/requirements-token-budget.txt
.\.venv\Scripts\python.exe -m py_compile evals/reviews/run_groq_eval.py evals/reviews/score_run.py evals/reviews/check_token_budget.py
.\.venv\Scripts\python.exe evals/reviews/check_token_budget.py
# Optional controlled inference after local preflight; model text is discarded:
.\.venv\Scripts\python.exe evals/reviews/check_token_budget.py --live
.\.venv\Scripts\python.exe evals/reviews/run_groq_eval.py --check-access
.\.venv\Scripts\python.exe evals/reviews/run_groq_eval.py --dry-run
.\.venv\Scripts\python.exe evals/reviews/run_groq_eval.py --run
.\.venv\Scripts\python.exe evals/reviews/score_run.py .eval-runs/reviews/<run-id>/run.json
# Complete the manual scores, then:
.\.venv\Scripts\python.exe evals/reviews/score_run.py .eval-runs/reviews/<run-id>/run.json --finalize
```

The selected contour is therefore suitable for the assignment as a free, asynchronous, source-language summarisation baseline with the limitations above. It is not evidence for synchronous maximum-volume throughput or high-quality abstractive consensus synthesis.
