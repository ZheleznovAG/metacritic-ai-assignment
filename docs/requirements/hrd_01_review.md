# HRD-01: bounded HTTP adapter and diagnosed field degradation

Task `HRD-01`. Requirements/risks per `implementation_plan.md#hrd-01`:
extended parser inputs from `IMP-02`/`IMP-04`; timeout, bounded
retries/rate limiting, 403/429/5xx, disappearing fields, route/cursor
mismatch and partial responses — every error diagnosed, never corrupting
good data. Current task/gate status belongs only to
[action_plan.md](../../action_plan.md).

This task closed across two cycles. The first cycle below covers only the
HTTP-adapter half of `HRD-01`'s own stated scope (its estimate splits
"corrupted HTML/SSR/backend fixtures" from "HTTP/failure/drift regression"
as two separate halves). The second cycle
([Parser-input extension: diagnosed field degradation](#parser-input-extension-diagnosed-field-degradation))
closes the remaining parser-input extension half, including `IMP-02`'s
documented known limitation.

## HTTP-adapter half

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

## Parser-input extension: diagnosed field degradation

## Scope of this cycle

Parser-level malformed-input coverage was reviewed and found substantial in
the HTTP-adapter cycle above (47 tests across `test_metacritic_parser.py`,
`test_metacritic_review_parser.py`, `test_metacritic_lists_parser.py`); it
scoped the one concretely documented, entirely-unaddressed gap left in that
coverage: `IMP-02`'s known limitation
([imp_02_review.md](imp_02_review.md), row "Degraded extraction"),
that a container being present but structurally broken (e.g. a future
markup/schema change) was indistinguishable from a genuinely empty score —
both silently reported `outcome=succeeded`, `metascore=None`/`userscore=None`
with no diagnostic signal.

Inspecting every fixture built under `IMP-02`/`IMP-03`/`IMP-04` (including
the two dedicated tbd fixtures, `bioeden_detail_tbd_userscore.min.html` and
`shatterverse_user_xbox_series_x_tbd.min.html`) confirmed a real,
live-grounded structural invariant on both affected fields:

- Every platform record in `__NUXT_DATA__` carries `criticScoreSummary` as a
  dict, on every observed fixture including the two tbd ones — only its
  `score` sub-field is ever `null` for a genuine tbd Metascore
  (`research/feasibility/metacritic-contract.md`: "tbd → null, не 0").
  `_parse_platform` previously treated *any* non-dict `criticScoreSummary`
  (missing key, wrong shape, or a future schema change resolving it to
  something else) exactly like a natural `null` score, with no distinction.
- The `global-score-wrapper` hero container is present on every observed
  detail-page fixture, including both tbd fixtures — a genuine tbd
  Userscore renders the container with no matching "User score ... out of
  10" title inside it, not by omitting the container. `parse_game_detail`'s
  lead-platform extraction previously never checked whether this container
  existed at all before treating "no match found" as `userscore=None`,
  unlike `parse_platform_userscore` (the separate per-platform page), which
  already made exactly this present-vs-absent distinction from `IMP-02`.

## Fix

`_parse_platform` now requires `criticScoreSummary` to resolve to a dict,
raising `MetacriticParseError` otherwise, before reading its `score`/`url`
sub-fields (which may still legitimately be `null`). `parse_game_detail`
now requires at least one `global-score-wrapper` container to exist before
calling `_extract_user_score` on it, raising if none is found; a `None`
result from a container that does exist is still the natural tbd case,
unchanged.

## Adversarial review

An independent `/code-review high` pass (full read of both diff hunks and
their enclosing functions, traced callers `gateway.fetch_game` →
`processing/runner.py` → `catalog/ingest.py`, empirically re-ran all 24
`test_metacritic_parser.py` tests plus strict mypy/ruff) found two items,
neither blocking:

- **Fixed:** the raised message for a malformed (present but non-dict)
  `criticScoreSummary` was identical to the one for a genuinely-missing key,
  which would mislead on-call triage of `candidate.last_error` into reading
  "missing" as "key absent" rather than "key present with the wrong shape."
  Split into two distinct messages (`"...has no criticScoreSummary key"` vs.
  `"...did not resolve to an object (got <type>)"`).
- **Accepted as a documented trade-off, not fixed this cycle:** both new
  checks raise per-platform, and `_parse_platform`'s exception propagates
  out of `parse_game_detail`'s platform list comprehension, failing the
  *entire* game's ingest the first time any single platform hits the
  anomaly — not just degrading that one platform's score field as before.
  Traced the full consequence: `gateway.fetch_game` catches
  `MetacriticParseError` into `game_dto=None`, `processing/runner.py` marks
  the candidate retryable and, after `MAX_AUTOMATIC_ATTEMPTS`, permanently
  `failed` with zero rows written for any of that game's platforms — even
  ones that parsed fine. This is not a new severity class introduced by
  this cycle: `_parse_platform`'s pre-existing id/name/slug/relatedGameId
  checks already fail the whole game the same way on a single platform's
  anomaly, and for the same underlying reason accepted under `IMP-02` — a
  field observed as always-present-in-some-shape on every real fixture, so
  its absence is evidence of a structural anomaly worth halting on rather
  than a per-platform edge case worth quietly tolerating. Silently
  excluding just the anomalous platform (or just its score) instead would
  reintroduce exactly the silent-degradation problem this cycle closes, one
  level down. If a genuinely new but legitimate platform-card shape (e.g. a
  new platform type Metacritic introduces) triggers this in the future
  before a parser update ships, that game's ingest pauses entirely rather
  than degrading partially — an availability/completeness cost accepted in
  exchange for never reporting a silently wrong or missing score as if it
  were a confirmed natural tbd.

## Verification

Two new regression tests in `test_metacritic_parser.py` reproduce each gap
by mutating the real Elden Ring detail fixture (not a hand-built minimal
payload), round-tripping its actual `__NUXT_DATA__` JSON through a small
helper (`_mutate_nuxt_payload`) for the Metascore case, and a plain
attribute-value string replace for the Userscore case:

- `test_malformed_criticscoresummary_raises_instead_of_reporting_a_natural_tbd`
  repoints one real platform record's `criticScoreSummary` at its own
  `name` field (a string, not a dict).
- `test_missing_lead_userscore_widget_container_raises_instead_of_reporting_a_natural_tbd`
  renames every `data-testid="global-score-wrapper"` occurrence in the real
  page.

Both were confirmed to fail against the pre-fix parser (`AssertionError:
MetacriticParseError not raised`) before the fix was restored, proving they
catch the real gap rather than passing vacuously. All 24
`test_metacritic_parser.py` tests and the full `scripts/check.py` suite (312
application tests, ruff format/lint, strict mypy, migration drift, static
build, all offline evals/verifiers) pass green locally.

This closes the parser-input extension half of `HRD-01`'s stated scope.
Combined with the HTTP-adapter half above, route/cursor-mismatch coverage
already verified under `IMP-03`, and the pre-existing 47-test malformed-input
suite, `HRD-01`'s full exit criteria are met; `HRD-01` moves to `Verified` in
`action_plan.md`.

Not covered here (an explicit, narrower scope boundary, not a regression):
building additional fixtures from other real games to exercise markup
variations beyond the two documented fields above is an open-ended
breadth expansion, not a closable gap — the two fields flagged as a known
limitation in `IMP-02` are the only concretely documented degradation risk,
and both are now diagnosed.
