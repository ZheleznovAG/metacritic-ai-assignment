# ADR-0005: Take on Bonus 1 (YouTube let's plays) after submission

- **Status:** Accepted (scope only), 2026-10-03. The technical contract stays Candidate until
  `YTP-02` freezes its examples and thresholds.
- **Amends:** [ADR-0002](0002-bonus2-scope.md) for the running service only. The submitted
  release `6ade911` and its gates (`GB`, `G7`) keep the `bonus2` scope they were accepted with.
- **Requirements/risks:** `YT-01`, `AC-YT-01…05`, `ASM-B01`, `ASM-B02`, `R-BON-YT-01`,
  `R-BON-YT-02`.

## Context

ADR-0002 chose Bonus 2 and dropped `BON-11`/`BON-12`. The assignment has since been submitted
and assessed; the reviewers may still open the service. The owner now wants a more capable
service and asked for Bonus 1: for each game find the most popular let's play on YouTube, turn
the blogger's narration into text, draw a conclusion from it and show it on the game card with
a link to the video.

## Decision

1. Bonus 1 is implemented as post-submission work outside the G-gates, tracked like the
   `MA-*` corrections in a separate queue (`YTP-01…04` in [action_plan.md](../../action_plan.md)).
   The historical `BON-11`/`BON-12` rows stay `Dropped` under ADR-0002.
2. The owner allowed unofficial tools: `yt-dlp` and `youtube-transcript-api`. Search and view
   counts use the official YouTube Data API v3 with the owner's key (`YOUTUBE_API_KEY`, kept in
   the ignored `.env.app`, never in Git).
3. Free tiers only, as for Groq summaries: the API key's 10 000 daily units and Groq's free
   limits bound throughput; work queues up instead of buying capacity.
4. The order follows the repository workflow: feasibility (`YTP-01`), frozen golden set,
   filter rules, rubric and budgets (`YTP-02`) before the method is tuned, then implementation
   (`YTP-03`) and the public slice (`YTP-04`).

## Consequences

- The feasibility result and its limits are in
  [research/feasibility/youtube.md](../../research/feasibility/youtube.md).
- Unofficial access can break when YouTube changes; a missing text or video is shown as an
  explicit reason on the card (`AC-YT-05`), never a made-up conclusion.
- Later commits on `main` remain post-submission work, distinct from the release that was
  sent for review.
