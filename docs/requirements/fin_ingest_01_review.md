# FIN-INGEST-01: source slugs beginning with a hyphen

2026-10-06. Requirements: SEL-01, DATA-01/02, RUN-01; risk R-EXT-01.
Status belongs to action_plan.md.

## Problem and frozen correction scope

Production run 483 became partial at 04:00 UTC; runs 484 through 493 failed
before processing. All ten failed fetches returned HTTP 200 for browse page 4
and were classified MetacriticParseError. This began before the edc0914 upgrade.
One read-only live probe reproduced the exact failure: the source has a valid
game-title record (ID 1300769260, slug `-aomi-`, title `-AOMI-`) and its listing
card links to `/game/-aomi-/`. The parser incorrectly required an alphanumeric
first character. The page contained 24 cards.

Keep the source slug unchanged. Accept lowercase alphanumeric/hyphen slugs with
at least one letter or digit. Keep canonical identity checks, record matching,
source order and pagination unchanged. Empty, hyphen-only, escaped, underscore
and multi-segment paths remain rejected. This is source-contract correction,
not a ranking or selection-policy change.

## Verification and adversarial review

Two new regression tests failed on the old parser with the live error and pass
after correction: both browse and New Releases retain the source ID and slug.
Negative controls reject malformed paths. All 71 parser/HTTP-adapter tests pass
offline, with no database or providers. Ruff lint and format checks pass.

Review checked malformed paths, matching Nuxt identity, source order and next-page
preservation, shared usage by both listing parsers, unchanged detail/review URL
handling, and incident timing. No database/schema or heuristic policy changes.

Production correction remains pending: server build, image identity, backed-up
upgrade and a real processing run must pass. HTTP and heartbeat checks alone
did not prove processing health in the previous release evidence.
