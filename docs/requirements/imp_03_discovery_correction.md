# IMP-03 discovery correction — 2026-09-13

Scope: [audit R02/R15](implementation_audit_2026_09_13.md), `SEL-02`,
`AC-SEL-03/04/06`, `NFR-02/04`, `R-TIM-01/02`, `R-EXT-04`, `R-TST-01`.
Current task/gate status remains in [action_plan.md](../../action_plan.md).
This is one local correction of existing discovery code. It does not complete
the outstanding hosted CI/public evidence for IMP-01/02 or start a new feature.

## Behavior and contract

[selector.py](../../app/processing/selector.py) formerly saved at most the remaining
batch capacity, then advanced past the entire SEE ALL page. The correction keeps
the checkpoint on a partially accepted page, rereads it next time and skips the
identities already persisted in the daily cycle. It preserves first source order
and deduplicates within each response as well as across pages. Existing pending
and retryable work consumes batch capacity before discovery; each batch remains
bounded by 20. Page/candidate acceptance and checkpoint/exhaustion changes remain
in one transaction under the existing fencing check.

A terminal page cannot exhaust the cycle while an unaccepted tail remains.
One New Releases game plus two 24-game SEE ALL pages now produce
`[1, 20, 20, 8, 0]`, all 49 ordered unique identities, and browse calls
`[1, 1, 2, 2]`. Both the partially consumed terminal page and the final zero-work
tick are covered by the regression.

Within a scan, an empty nonterminal page or repetition of a previously seen
identity set stops discovery at the problem page. The comparison also catches
nonconsecutive repetitions and reordered duplicates. Different known-only pages
can still be traversed. A scan admits at most 100 page requests and no new request
after 60 seconds of monotonic elapsed time. These are resumable operational bounds,
not a claimed source maximum, throughput measurement or forced HTTP/DB/core deadline.
Already fetched pages are committed and selected core work is processed.

[scheduler.py](../../app/processing/scheduler.py) persists the specific discovery
error from the batch result. A stopped scan is `partial` if some core processing
succeeded, otherwise `failed`; it keeps `browse` and its saved checkpoint.
Only accepted source termination can set `exhausted`. The next scheduled slot can
resume from the saved position. The precise contract is in
[design.md](../design.md#почасовая-обработка).

## Executable evidence

All tests use fake gateways/clocks and the separate Django test database on
PostgreSQL 16. No live Metacritic/AI calls or deployment were made.

[test_processing_discovery.py](../../app/tests/test_processing_discovery.py) adds
11 integration regressions through the real `run_tick → run_batch → core` path:

| Exit criterion / counterexample | Executable evidence |
|---|---|
| Union/order/uniqueness of every batch, including a terminal tail and final zero | `test_all_page_tails_are_processed_before_exhaustion` |
| Exact repeats stop, preserve cursor and resume after source recovery | `test_repeated_pages_stop_without_false_exhaustion_and_can_resume` |
| Cross-page overlap and in-page/New Releases duplicates keep first order | `test_duplicates_and_overlap_preserve_first_source_order` |
| Retry consumes capacity; terminal remainder survives | `test_retry_occupies_capacity_without_discarding_terminal_page_tail` |
| Failed reread cannot discard the partial-page tail | `test_failure_rereading_partial_page_retains_cursor_and_tail` |
| Failure at checkpoint write rolls back new identities too | `test_page_and_candidates_roll_back_together_on_checkpoint_failure` |
| Crash after discovery commit recovers the pending batch, then the tail | `test_crash_after_discovery_commit_recovers_pending_batch_then_page_tail` |
| Empty nonterminal response cannot claim exhaustion | `test_empty_nonterminal_page_stops_at_same_cursor` |
| Reordered/nonconsecutive loop stops while retaining earlier progress | `test_nonconsecutive_reordered_repetition_stops_after_saved_progress` |
| 100 distinct overlapping known-only pages stop by request budget and resume | `test_page_budget_defers_distinct_known_pages_and_resumes` |
| 60-second admission boundary commits fetched work, prevents next HTTP, resumes | `test_elapsed_budget_stops_new_requests_but_commits_fetched_page` |

Before the implementation edit, the first two tests failed on `aac44da`: counts
were `[1, 20, 20, 0, 0]`, and repeated-page discovery reached the test's sixth-request
safeguard. After the edit, all 29 discovery/selector/scheduler tests passed, including
the existing same-hour idempotency, lease-loss and daily-boundary tests.
The new tests are automatically discovered by the existing local/container/CI
`scripts/check.py` path; no optional test command or dependency is introduced.

Reproducible full verification command (setup in [README](../../README.md)):

```powershell
.\.venv-app\Scripts\python.exe -B scripts/check.py
```

Run 2026-09-13 after the implementation edit, local Python 3.12 / PostgreSQL 16:
ruff format/lint, mypy, Django checks and migration drift all passed; application
suite `177 tests, OK` (166 pre-existing + the 11 new discovery regressions above);
scripts/tests `6 tests, OK`; planning checks and `18 tests, OK`; saved AI run
`7 tests, OK`; selection `9 tests, OK`; frozen selection oracle and the production
candidate verifier both passed (`all_pass=True`). Exit code 0 end to end. Local
intermediate logs are in ignored `.artifacts/imp03-correction/`; the committed
tests are the durable reproduction mechanism.

## Adversarial review and limits

The correction author reviewed the diff against the requirements, acceptance
criteria, risks, original probes and transaction boundaries. No separate-agent
review is claimed. The review specifically challenged a terminal page larger than
remaining capacity, retries taking one slot, duplicate identity insertion, crash
on either side of the page transaction, HTTP failure while rereading, legitimate
known-only overlap, reordered loops, and both admission limits. These checks are
the executable regressions above, not evidence inferred merely from ORM uniqueness.

Rereading a mutable external page is not a frozen source snapshot. Inserts/removals
between requests can shift positions; SPK-04 already records that source limitation.
No existing cycle is reset: a historically advanced/exhausted checkpoint cannot be
repaired from discarded data. A subsequent day's ordinary scan uses the corrected
logic. The repetition set is local to each scan; repeated bad responses on later
hourly retries remain bounded and diagnosable, without claiming source exhaustion.
The time bound prevents further request admission and does not interrupt a request
already in flight or bound total core processing duration. Global capacity,
hardening and current hosted/public verification require their own evidence.

The other 13 audit findings concern reviews, AI and UI and are not fixed by this
correction or by passing the pre-existing tests. Historical review documents are
preserved; this correction does not retroactively validate their broader claims.
