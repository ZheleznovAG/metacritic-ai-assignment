# Implementation audit received 2026-09-13

This is the findings index for the owner's review of `93016a5` through
`aac44dab64535e8a2eb35a071ba988bd22efb149`. It preserves all 15 material findings
(7 P1, 8 P2), including the eight reproduced findings from the
[previous audit](implementation_audit_2026_09_12.md). Current correction/task/gate
statuses belong only to [action_plan.md](../../action_plan.md).

The supplied report, executable probes and original output remain in the ignored
`.artifacts/review-20260913/` directory. This index attributes the observations below
to that review; it does not claim that the correction author independently reran
all 18 probes. Their assertions confirm defective behavior and must be converted
to desired-outcome application regressions for each correction.

| ID | Priority / task | Observed counterexample on the reviewed SHA | Requirement / risk | Original probe |
|---|---|---|---|---|
| R01 | P1 / IMP-04 | Ten 450-token reviews produce 19,060 estimated prompt tokens through mock HTTP, exceeding the 6,000 full-payload limit | AI-01/02, R-AI-02 | `test_13` |
| R02 | P1 / IMP-03 | One initial game plus two 24-game pages yield 41 of 49 games before false exhaustion | SEL-02, AC-SEL-03/04/06, R-TIM-01 | `test_01` |
| R03 | P1 / IMP-04 | Next day's unchanged three reviews yield three observations but unique_count=0 and unstable | AI-03, AC-AI-05, NFR-04 | `test_02` |
| R04 | P1 / IMP-04 | Changed texts reuse the old corpus/input; score-only edits retain the old score | AI-03, AC-AI-05, NFR-04 | `test_03`, `test_15` |
| R05 | P1 / IMP-04 | A pending collection contributes a fourth review to a corpus with reported_count=3 | AI-01/02, NFR-04 | `test_04` |
| R06 | P1 / IMP-04 | Crash after terminal collection commit leaves no corpus/job and ordinary reclaim finds no work | AI-01/02, NFR-01/02 | `test_05` |
| R07 | P1 / IMP-04 | Unknown support R99 is dropped while the summary succeeds with zero claims | AI-01/02, AC-AI-01/02 | `test_07` |
| R08 | P2 / IMP-04 | First fetch failure after five successful pages exhausts retry budget | NFR-02/04, AC-AI-06 | `test_06` |
| R09 | P2 / IMP-04 | Two PostgreSQL connections admit 13,600 reserved tokens against TPM=8,000 | NFR-03, R-AI-02 | `test_16` |
| R10 | P2 / IMP-04 | Four HTTP calls share one attempt/reservation; reclaim leaves the expired attempt open | NFR-02/05, R-AI-02 | `test_11`, `test_18` |
| R11 | P2 / IMP-04 | Delivering the same collection claim twice issues another HTTP call and corrupts complete to unstable | NFR-03 | `test_10` |
| R12 | P2 / IMP-05 | Pending collection is shown as ok; equal corpus timestamps can select the older result | UI-02, AC-UI-02/06, R-UI-01, R-TST-01 | `test_08`, `test_09` |
| R13 | P2 / IMP-04 | JSON status=[] raises unclassified TypeError instead of retry | AC-AI-06, NFR-02/04 | `test_14` |
| R14 | P2 / IMP-04 | Available collection work prevents ready summary jobs from being considered despite free quota | AI-01/02, R-AI-02 | `test_12` |
| R15 | P2 / IMP-03 | Repeating a nonterminal SEE ALL page makes unbounded requests without progress | SEL-02, NFR-02/04, R-EXT-04, R-TIM-02 | `test_17` |

The review reports 18/18 defect-confirming probes. Linux checks passed 166
application tests and the permissions/deployment, planning and frozen eval checks.
The local application suite had one stale-state failure; an additional equal-timestamp
probe made that ordering defect deterministic. Existing green suites therefore do
not establish the missing contracts.

The review independently reproduced `aac44da`'s image builds, offline tokenizer,
fresh provisioning/migrations/web/Caddy chain and HTTP/CSS smoke. It found no new
material defect in that container correction. Hosted CI and the current public VDS
were not verified; neither the report nor this index closes that evidence gap.
Similarity, browser E2E, permanent deployed scheduler/worker services and public
operational checks also remain outside that demonstrated result.

Original artifact SHA-256 values, measured while incorporating this review:

| Local artifact | SHA-256 |
|---|---|
| `review.md` | `c431f292d410d054e680efed2c297a0d9778651c4e75a973c18a8c885359a8dd` |
| `reproduce.py` | `0b60be63ee0053b7dc206079fb48ee76f8f97aca64662d7ea0edfa08668bcdef` |
| `probes.log` | `086835d05e6cdc2f7f3933fa38bc371d897196d0936ff6c5a6974c96d24cac1a` |

The hashes identify the supplied artifacts; they do not replace committed
executable evidence. The discovery correction's desired-outcome tests and
verification are recorded in [imp_03_discovery_correction.md](imp_03_discovery_correction.md).
