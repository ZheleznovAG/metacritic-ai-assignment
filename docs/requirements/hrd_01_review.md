# HRD-01: bounded HTTP adapter (HTTP-adapter half)

Task `HRD-01`. Requirements/risks per `implementation_plan.md#hrd-01`:
extended parser inputs from `IMP-02`/`IMP-04`; timeout, bounded
retries/rate limiting, 403/429/5xx, disappearing fields, route/cursor
mismatch and partial responses — every error diagnosed, never corrupting
good data. Current task/gate status belongs only to
[action_plan.md](../../action_plan.md).

**This cycle covers only the HTTP-adapter half** of `HRD-01`'s own stated
scope (its estimate splits "corrupted HTML/SSR/backend fixtures" from
"HTTP/failure/drift regression" as two separate halves). The parser-input
extension half — including `IMP-02`'s documented known limitation that
extraction degradation is indistinguishable from natural field absence — is
not addressed here and remains open for a follow-up cycle. `HRD-01` stays
`In progress` in `action_plan.md`, not `Verified`, until that half closes
too.

## Scope of this cycle

`app/metacritic/gateway.py`'s own docstring had, since `IMP-02`, explicitly
read "no retry/backoff policy (that is `HRD-01`)" — zero in-call retry
existed. Parser-level malformed-input coverage (`test_metacritic_parser.py`,
`test_metacritic_review_parser.py`, `test_metacritic_lists_parser.py`: 47
tests total from `IMP-02`/`IMP-04`) was reviewed and found already
substantial; route/cursor-mismatch handling was already fixed and tested
under `IMP-03`. This cycle scoped tightly to the concretely audited,
entirely-unaddressed gap: the HTTP adapter itself had no bounded retry and
no bound on total response time or size, matching the independent audit's
(`docs/requirements/implementation_audit_f0e89a4.md`) finding `A07`:
`REQUEST_TIMEOUT_SECONDS` only bounds each individual connect/read/write/pool
operation, never the total duration of a slow, steadily-trickling response,
and never bounds response size at all.

## Fix

`MetacriticGateway._get`/`_attempt` now stream the response
(`client.stream("GET", url)` + `iter_bytes(chunk_size=65536)`) instead of a
single buffered `client.get(url)`, tracking total bytes and elapsed wall-clock
time across the whole read — independent of httpx's own per-chunk timeout —
and aborting with `response_too_large`/`response_deadline_exceeded` if either
bound (`MAX_RESPONSE_BYTES=8MiB`, `RESPONSE_DEADLINE_SECONDS=30s`) is
crossed. A bounded in-call retry (`MAX_ATTEMPTS=3`, fixed backoff
`(0.5, 1.0)`) applies only to genuinely transient failures — transport-level
errors (connection reset, timeout, protocol error) and 5xx status codes;
403/429 are not retried in-call, matching how every other retry in this app
already works (the outer hourly/daily cycle retries failed work on its own
schedule, rather than spinning against a live rate limit inside one call).
Response compression is disabled (`Accept-Encoding: identity`) on the
default client.

## Adversarial review

Two independent `/code-review high` passes found and fixed three real bugs
before commit:

- **Fixed (crash on essentially every request):** the first draft called
  `response.content`/`.text` after manually exhausting `iter_bytes()`.
  Verified directly against the installed httpx: unlike calling
  `response.read()`, manually iterating a stream to completion does **not**
  populate httpx's internal content cache, so `.content`/`.text` raise
  `httpx.ResponseNotRead` — a `RuntimeError` subclass, not an
  `httpx.HTTPError` — crashing every normal 200 response (and every
  403/429/5xx) instead of returning it. The new test suite's first draft
  passed anyway only because it constructed `httpx.Response(200,
  content=b"...")` with a plain `bytes` literal, which httpx eagerly
  `.read()`s at construction time and so never hit the real streaming path a
  genuine network transport (or `MockTransport` given a generator) exercises
  — masking exactly the bug it should have caught. Fixed by accumulating
  bytes into a `bytearray` manually during the loop and decoding/hashing
  that directly; every test response body was switched from a `bytes`
  literal to a one-shot generator to force the real lazy path, and a new
  multi-chunk reassembly test was added.
- **Fixed (real bug):** `except httpx.HTTPError` classified every httpx
  error as retryable, including non-transient ones (`httpx.DecodingError` on
  malformed content-encoding, `httpx.TooManyRedirects`) that would fail
  identically on retry. Narrowed to `except httpx.TransportError` (retryable)
  before the broader `except httpx.HTTPError` (not retryable); a dedicated
  test (`test_a_non_transport_http_error_is_not_retried`) confirms a
  `DecodingError` is surfaced immediately, once, without a wasted retry.
- **Fixed (real, narrower gap):** `MAX_RESPONSE_BYTES` bounds the
  *decoded* byte count as `iter_bytes()` yields it, but httpx transparently
  decompresses `Content-Encoding` responses before that check ever runs —
  one `decode()` call on a small compressed chunk (a compression bomb) could
  spike memory before the size check has a chance to react, which the code's
  own comment overclaimed as fully closed. Disabled response compression via
  `Accept-Encoding: identity` on the client, which removes the gap for any
  server that honors the request (normal web servers do); documented that a
  source which ignored it anyway is not defended against here, rather than
  re-overclaiming a guarantee the fix doesn't fully provide. A dedicated
  test confirms the header reaches the default client.

Also addressed as a small robustness fix (not from either review, self-
caught while responding to the reviews): `RETRY_BACKOFF_SECONDS[attempt]`
would raise `IndexError` on a future retry if `MAX_ATTEMPTS` were increased
without extending the backoff tuple to match; added an explicit
module-import-time check that fails loudly instead.

**Accepted as a documented trade-off, not fixed this cycle:**
`processing/selector.py`'s `BROWSE_TIME_LIMIT_SECONDS` (a soft 60s admission
cap on one discovery scan) checks its deadline only *between* whole
`iter_browse()` calls, not during one. Since a single call can now take up
to roughly `MAX_ATTEMPTS` attempts' worth of `RESPONSE_DEADLINE_SECONDS`
plus backoff on transient failures, a call starting just under the deadline
can push the actual scan meaningfully past it in that worst case — a
genuine, real consequence of this cycle's own change. `selector.py`'s
existing docstring already frames this bound as "admission bounds for one
discovery scan, not a source-volume/exhaustion limit," not a hard latency
guarantee, and the loop still correctly terminates (bounded, not unbounded,
worst-case latency) with every existing invariant intact (partial pages
still handled correctly, the cursor still isn't advanced past what wasn't
consumed). Redesigning `selector.py`'s own timeout architecture to check the
deadline mid-call would expand this cycle beyond its audited scope; the
constant's comment was updated to state the new worst case explicitly
rather than leaving it silently stale.

## Verification

310 application tests (12 added: `test_metacritic_gateway.py`'s 12 cases
covering oversized/slow responses without retry, transient-failure retry to
success and to exhaustion, non-transport-error no-retry, 5xx retry, 403/429
no-retry, retry-bound exhaustion regardless of status, a normal single-chunk
response, a multi-chunk reassembly, and the default client's compression
header), full `scripts/check.py` (ruff format/lint, strict mypy on 112
source files, Django checks, migration drift, static build, all offline
evals/verifiers) — all green locally. Every one of the `ResponseNotRead`-
catching tests was directly confirmed to fail against the pre-fix code
(`httpx.ResponseNotRead` raised on 7 of 11 cases) before the fix was
restored, proving the tests catch the real bug rather than passing
vacuously.

Not covered by this cycle (left for `HRD-05`/future hardening): a genuinely
malicious server that ignores `Accept-Encoding: identity` and sends a
compressed compression bomb anyway is not defended against; catalog/review
call sites (`catalog/ingest.py`, `reviews/collector.py`) were not audited
for their own handling of the new retryable/error-code surface beyond
confirming the full application suite (including their own existing tests)
still passes unchanged.
