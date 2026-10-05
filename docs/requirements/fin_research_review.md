# FIN-RESEARCH: freeze existing policies with disclosed quality limits

Baseline: FIN-DOCS `500305a`, 2026-10-05. Requirements/risks: `SIM-01–03`,
`YT-01`, `AC-YT-04/05`, `R-SIM-01`, `R-BON-YT-02`, `R-TST-01`.
Task and gate decisions belong only to [action_plan.md](../../action_plan.md).

## Scope and exit criteria frozen before work

The tracker permits independent holdout **or explicitly accepted limitations**.
Use the existing owner decisions [ADR-0004](../decisions/0004-foreign-description-gate.md)
and [ADR-0006](../decisions/0006-letsplay-conclusion-accepted-with-limitation.md).
No new acceptance waiver, ranking formula, contour, labels or threshold is introduced.
No existing evaluation set is renamed an independent holdout.

- Pin active research policies, prompts/schemas, labels, reports, metrics and scorer
  source by SHA-256; verify the freeze against the working tree.
- Recompute available offline evidence from original hash-matching saved inputs.
  Separate historical replay/integrity from independent semantic-quality evidence.
- Preserve similarity's cross-set regression and Let's Play's failed quality bar.
  Freeze existing evaluation sets against further tuning; retain experimental status.
- Document a preregistered future holdout protocol and stop/reopen rules. Future
  collection/independent grading is deferred, not silently marked completed.
- Negative controls reject changed artifacts, missing cases, optimistic acceptance
  claims and replacement inputs. No paid/provider calls or private text publication.
- Run appropriate offline/integration checks, record evidence and review limitations.

## Review and evidence

The [research contract](../research_freeze.md) maps the stop rule to the existing
owner decisions. Independent holdout collection/grading is explicitly unexecuted;
future protocols are proposed, not accepted or used to retune a method.

Evidence and outcome:

- [Freeze manifest](../evidence/fin-research/freeze.json) and
  [independent audit](../evidence/fin-research/audit.json): 83 source/data/evidence files
  pinned, complete cases checked, original failures preserved. Five model assets
  were hashed independently from the offline image.
- [Image/source check](../evidence/fin-research/image_match.json) confirms application,
  evaluator and dependency bytes match the freeze, together with actual model assets.
- [Similarity replay](../evidence/fin-research/similarity_replay.json): original
  1196-game snapshot hash matches; the Linux replay does not exactly match historical
  numbers. Set-2 current nDCG is 0.548, not historical 0.570. Repeating the Linux run
  exactly reproduces the entire emitted aggregate/per-query report. This does not
  assert equality of every unreported catalog ranking. Historical-report drift's
  cause is unresolved; no report is overwritten and no criterion is waived.
- [Let's Play replay](../evidence/fin-research/letsplays_replay.json): original saved
  speech hashes, actual selection trace and repeat determinism match. All 14 saved
  transcripts match hashes; contour fingerprint, structural validation, token
  reservations and quote materialization reproduce. No provider call or new grading.
- [Checks](../evidence/fin-research/checks.txt): 29 similarity, 10 Let's Play and 8
  freeze negative-control tests pass. Missing/duplicated cases, changed/missing/new
  files, path escape and false holdout claims are rejected. The historical selection
  scores 18/20; conclusion remains 111/132 with blocking LP-04 and failed mandatory
  criteria. Passing integrity tests is not passing semantic quality.
- [Verification record](../evidence/fin-research/verification.json) records image IDs
  and the empty application/original-eval diff from `500305a`. Appropriate checks
  are the offline integrity/replay checks; no application patch was introduced.
  The full canonical application suite was verified in FIN-DOCS; fresh release
  verification belongs to FIN-RELEASE.

## Adversarial review

The review checked dataset reuse, grader independence, denominator omission,
unjudged candidates, false positives, sparse descriptions, version/threshold drift,
quote-versus-attribution confusion, token units and raw-input privacy. No old set
was promoted to holdout, failed criterion relabeled as pass or provider output
treated as an independent judge. Replay tooling was corrected before freezing and
verified against saved traces/outputs; original datasets and policies are unchanged.

Scope is a reproducible freeze with explicitly bounded evidence, not certification
of recommendation/semantic quality or exact historical model reproducibility.
The current model assets and Linux replay are now pinned; the original report did
not pin its model binary/environment. That historical evidence gap stays visible.
Let's Play remains experimental under ADR-0006; similarity retains ADR-0004's
accepted regression. Original acceptance thresholds stay unchanged. No new acceptance
waiver is inferred from the authoring of this review.
