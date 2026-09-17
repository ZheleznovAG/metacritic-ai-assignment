# REL-03: AI-assisted history archive

Date: 2026-09-17. Connections: `DEL-03`, `AC-DEL-03`, `ASM-23`, `ASM-26`. Prepares
(does not itself send) the archive `assignment.md` allows as raw JSONL. Current status
belongs only to [action_plan.md](../../action_plan.md).

## What is included

Claude Code (this project's own AI-assistant tool) keeps one raw JSONL transcript per
session under the local `~/.claude/projects/<this-project>/` directory. That directory
holds **11 session files**; one (`0d349523...`) is a byte-identical 611-line prefix of
another (`16ac777e...`) -- a resumed/forked session that Claude Code copies forward
rather than truncates -- so it is excluded as a pure duplicate, not an omission (every
line it contains is already present in `16ac777e...`). The remaining **10 sessions**,
20,328 JSON lines total, are exported as raw JSONL, one file per session, renumbered
`01_`–`10_` by real start time (the UUID in each filename is the original session ID):

| # | Session | Start (UTC) | End (UTC) | Lines |
|---|---|---|---|---|
| 01 | `2a02eaae` | 2026-09-11 06:01 | 2026-09-11 08:08 | 900 |
| 02 | `31b086cf` | 2026-09-11 08:11 | 2026-09-11 10:30 | 682 |
| 03 | `f1836f58` | 2026-09-11 08:30 | 2026-09-12 05:44 | 6,837 |
| 04 | `1b633d4b` | 2026-09-13 02:01 | 2026-09-13 02:45 | 149 |
| 05 | `759927cf` | 2026-09-13 04:23 | 2026-09-13 06:56 | 203 |
| 06 | `491a2662` | 2026-09-14 09:28 | 2026-09-14 09:57 | 749 |
| 07 | `c9109107` | 2026-09-14 10:01 | 2026-09-14 16:01 | 958 |
| 08 | `16ac777e` | 2026-09-15 06:07 | 2026-09-16 05:46 | 2,728 |
| 09 | `aca3afc5` | 2026-09-15 16:57 | 2026-09-16 05:49 | 4,242 |
| 10 | `f6209bd4` | 2026-09-16 10:33 | *cutoff (ongoing)* | 2,880 |

Sessions 02/03 and 08/09 overlap in time -- genuinely parallel/concurrent Claude Code
sessions (the same pattern `action_plan.md` already records for `IMP-02`'s independent
`metacritic-ai-assignment-dc` review session), not an ordering error. Session `10` is
**this session, still in progress** at the time of export; the cutoff is the export
timestamp below, not an arbitrary earlier point.

**Cutoff**: 2026-09-17 (export run during session 10; that session's own file stops at
whatever it had written up to the export, not at its eventual end).

## Forced omission (documented, not hidden)

The repository's first commit is 2026-09-01; the earliest available Claude Code session
starts 2026-09-11. **No raw session log exists on this machine for that ~10-day window**
-- the repository init, the multi-provider methodology exploration (`research/methodology/`,
which independently queried ChatGPT/Codex/DeepSeek/Grok/Qwen and is already committed as
markdown, just not as this tool's raw JSONL) and the early planning gates (`G0`–`G2`,
`PLN-01`–`PLN-03`) predate this local session history. This is a genuine gap in what is
available to export, not a redaction: nothing from that period has been removed, because
nothing from that period exists here to remove. `research/methodology/` and the dated
`docs/requirements/*.md` review documents remain the available record of that period.

## Secret/privacy inspection

Every session file was processed by a redaction pass (script and exact patterns kept for
audit in `.artifacts/rel03-ai-history/redact.py`, itself gitignored like the archive) with
two independent layers, deliberately **not** a bare hex/length heuristic -- these
transcripts are full of *legitimate* long hex strings (commit SHAs, Docker image IDs,
sha256 checksums) that are the actual evidence and must survive untouched:

1. An exact-value denylist for every real secret this session could enumerate with
   confidence: the local `.env`/`.env.app` credentials (Groq API key, GitHub deploy token,
   Django secret key, all six PostgreSQL role passwords) and the one production VDS
   credential read earlier in this same session. 874 exact-value matches redacted.
2. A generic `KEY=value`/`KEY: value` pattern (including the numbered-line shape
   `Read` tool output uses) whenever the key name suggests a credential (`PASSWORD`,
   `SECRET`, `TOKEN`, `API_KEY`, `GROQ`, `GITHUB_SSH`, `DEPLOY_SSH`, `PRIVATE_KEY`) --
   this catches secrets whose *specific value* isn't in the denylist above (for example
   any credential from an earlier, since-rotated generation this session never read),
   as long as its key name was visible. 1,132 pattern matches redacted. A handful of
   these are CI's own intentionally-public placeholder value
   (`ci-only-...-never-use-in-production`, visible unredacted in the committed
   `.github/workflows/ci.yml` already) swept up by the same broad rule; over-redacting a
   harmless placeholder costs nothing real.

Verified after redaction, against the actual archived files:

- All 11 known secret values: **zero** occurrences remain anywhere in the archive.
- Legitimate identifiers (a real commit SHA, a real Docker image ID) spot-checked:
  **present and untouched**, confirming the redaction did not also destroy the evidence
  the archive is supposed to carry.
- All 20,328 lines across all 10 files: **valid, parseable JSON** after redaction (the
  substitution operates on parsed string values and re-serializes, not on raw text, so a
  broken line would mean a bug, not a stray match; none were found).

This session found no third-party personal data to redact (a solo project; people other
than the repository owner are never named in these transcripts, matching this tool's own
role-based-reference convention). The owner's own name/email are not redacted -- they are
the applicant submitting their own assignment, not third-party PII.

**This automated pass is a strong first layer, not a substitute for the owner's own spot
check before anything is actually sent** -- REL-05 should not skip a manual skim of a
sample before attaching this archive to the delivery email.

## Where the archive is

`.artifacts/rel03-ai-history/ai-history.zip` (gitignored, like every other local-only
build/evidence artifact under `.artifacts/`; not committed -- `assignment.md` asks for
this alongside the repository link, not inside the repository itself).
SHA-256 `1b2eec7d5ea08218a05b81421544532d993da52b8f8fd954f331431477d665f2`.
12,154,456 bytes, 10 files, `01_`–`10_` as listed above.

## Boundaries

- This archive covers only this local machine's Claude Code sessions for this project
  directory. If any AI-assisted work happened through a different tool, machine, or
  account, it is not captured here beyond what already exists in the repository as
  markdown (`research/methodology/`).
- The redaction denylist's specific values are only as complete as this session's own
  knowledge of them; the generic key-name pattern is the real safety net for anything
  outside that denylist, and was verified to fire broadly (1,132 matches) across every
  session file, not just this one.
