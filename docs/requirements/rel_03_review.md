# REL-03: scoped AI history and privacy verification

Date: 2026-09-17. Requirements: `DEL-03`, `AC-DEL-03`, `NFR-06`; assumptions:
`ASM-23`, `ASM-26`. Current task/gate status belongs to [action_plan.md](../../action_plan.md).

## Inclusion follows repository evidence

The delivery window starts on **2026-09-01, Asia/Novosibirsk**. A matching date or
working directory is only a discovery filter. Every candidate has an explicit decision
in the [session-to-Git selection](../evidence/ai-history-selection.json), with repository
artifacts, related commits, the kind of work and the reason for inclusion or exclusion.

The archive contains **29 main conversations (18 Codex, 11 Claude Code) and 44
substantive Claude review workers**. Planning, methodology, review and preparation for
delivery remain relevant even without an authored code commit. The recorded commit
references establish association, not exclusive authorship: sessions overlapped, and
some changes were committed by another conversation. Existing Git subjects and artifacts
were checked because earlier privacy maintenance changed historical commit IDs.

Concrete content checks, rather than date matching:

- The Codex methodology answer has 35 of 36 substantive lines in the saved
  [iteration-0 answer](../../research/methodology/iteration_0/result/codex_5.6_sol_xhigh.md),
  committed in `0fba5fc`.
- The final-methodology session contains all 112 substantive lines of the saved
  [iteration-1 answer](../../research/methodology/iteration_1/result/codex_5.6_sol_xhigh.md).
- The comparison discussion reads all eight preserved source answers. Its intermediate
  best/comparison/audit drafts are not retained in Git; it is included as preparation,
  not presented as a separately committed deliverable.
- Ingestion review findings are independently documented in the
  [IMP-02 review](imp_02_review.md); they belong even though that reviewing session
  did not create the implementation commit.

Within the window, eight records are omitted: a greeting, an interrupted request with
no answer, four internal permission-check workers identified by their `session_meta`
source, a resumed conversation prefix, and a placeholder-only worker. The prefix check
compared **all 288 user/assistant UUIDs and message bodies in order**. These messages
are retained in the continuation; the JSONL files themselves are not byte-identical.
No substantive discussion is excluded merely because it contains no code.

## Privacy and integrity

The [exporter](../../scripts/export_ai_history.py) rebuilds from the two local stores,
uses the reviewed selection, preserves each retained file's record order, and refuses
unreviewed candidates, missing sources, malformed JSON or an incomplete written tail.
Files are numbered by their earliest recorded timestamp, including session metadata;
overlapping conversations are not asserted to form one serial execution.

Redaction covers exact private values supplied in an ignored local file, credential
fields and assignments, common token/private-key/authentication shapes, credential URLs,
nested JSON arguments, local home paths, email addresses and private login contexts.
Opaque image payloads are replaced with explicit markers because their pixels cannot be
verified by the text scan. Numeric usage records and commit/image hashes are preserved.
Private-value files, source logs, environment files and helper caches are not packaged.

The [audit manifest](../evidence/ai-history-audit.json) records the actual archive hash,
per-file hashes, timestamps, line counts and redaction counters. The ZIP contains only
selected sanitised JSONL files and `manifest.json`. It is stored locally at
`.artifacts/rel03-ai-history/ai-history.zip`, outside Git.

The independent scan rejected an intermediate export: a truncated OpenSSH private-key
block lacked its closing marker and survived the earlier complete-block pattern. The
exporter now removes incomplete blocks and recognizable headerless OpenSSH fragments;
Windows paths in MSYS/WSL notation are also covered. Dedicated counterexamples protect
both fixes. No original key material or private machine path is quoted in this review.

Verification: 15 adversarial exporter/verifier tests, Ruff, archive CRC/JSON checks, exact-value
residual checks, and a separate content scan. The tests cover sibling-directory
confusion, timezone boundaries, interrupted writes, unreviewed sessions, nested/quoted
credentials, image payloads and preservation of legitimate identifiers. They run in
`scripts/check.py` and CI through the existing scripts test discovery.

Raw conversations contain credential/private-data matches and must not be sent directly.
Zero detected residuals in the sanitised archive is bounded evidence, not a guarantee
that every possible secret format has been recognised; no credential is claimed revoked
or invalid merely because it is old. The independent verification results are recorded
in [ai-history-verification.json](../evidence/ai-history-verification.json).

## Cutoff and limitations

The manifest describes a local snapshot, not a final delivery. The current conversation
can grow after export. `REL-05` must review new candidates, re-export, rerun the privacy
checks and confirm the attachment hash immediately before sending.

Only locally available Codex/Claude logs are reconstructed. Other model answers already
saved in `research/methodology/` remain repository evidence; their original external chat
histories cannot be reconstructed from those Markdown files. No claim of continuous
coverage or recovery of missing conversations is made. The Git-history change and local
archive preparation do not themselves publish, deploy or send the deliverable.
