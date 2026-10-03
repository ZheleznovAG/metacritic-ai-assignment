# ADR-0006: Show let's-play conclusions from contour 2.1.0 with a disclosed limitation

- **Status:** Accepted by the owner, 2026-10-03, with one unmet frozen criterion (below).
- **Context:** [ADR-0005](0005-bonus1-after-submission.md) (Bonus 1 after submission), task `YTP-03`.
- **Requirements/risks:** `YT-01`, `AC-YT-04`, `AC-YT-05`, `R-BON-YT-02`.

## Context

The let's-play conclusion was evaluated on the frozen set
([metric.md](../../evals/letsplays/metric.md), cases `1.0.1`) in four contour versions
([conclusion_results.md](../../evals/letsplays/conclusion_results.md)). Versions 1.0.0 and 1.1.0
let the model write quotes and it invented or paraphrased some. From 2.0.0 the model cites
numbered transcript segments, so every shown quote is the transcript itself and all 14 answers
pass the local checks.

The frozen rubric bar is still not met. Version 2.1.0 scores 111 of 132 (84.1% against 85%);
one blocking error remains (the Pokopia interface text "Environment level terrible" given as the
creator's dislike), and momentary reactions such as a scare or sarcasm after a mistake are
sometimes counted as dislikes. The video selection itself passes its own bar (18/20).

## Decision

The owner chose to show conclusions from contour `letsplay-conclusion` 2.1.0 as they are, rather
than iterate further, show only the verdict, or show only the video link.

- Every like and dislike is shown with its verbatim transcript segment, so a reader can see
  what it rests on.
- The card says that the conclusion is an AI reading of the first minutes and can mistake a
  reaction for an opinion.
- The frozen bar is not lowered and the set is not relabelled; a later contour must pass it, or
  be accepted again with its own result.

## Consequences

- `YTP-03` is closed with this accepted limitation; `YTP-04` deploys it.
- A future contour change runs the same 14 cases and `score_conclusions.py` before replacing 2.1.0.
- The limitation is visible in the product, not only in this repository.
