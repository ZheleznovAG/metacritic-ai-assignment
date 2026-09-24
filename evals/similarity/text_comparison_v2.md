# Real-catalogue text comparison, second set (2026-09-24)

Follows [`text_comparison.md`](text_comparison.md) (set 1.0.0, 11 queries), which stays frozen. The
first set was graded with the proposing methods visible and its floor was tuned on the same labels
([ADR-0003](../../docs/decisions/0003-text-hybrid-similarity.md)). This set fixes both: labels, metric
and acceptance bar are committed before any candidate policy is tuned.

## Labels

[`text_labels_v2.json`](text_labels_v2.json): 24 games drawn with a fixed seed from the 1196-game
catalogue snapshot, **including games without a description** (the running policy gives those no
similar games at all). For each query the pool is the union of the top five of six methods (see the
file); candidates were graded shuffled, without method names or scores.

The catalogue carries many legacy app descriptions that belong to other games (a "third person
shooter" described as a slot machine). The grading rule therefore reads a game as its **title and
genre**, and its description only when it agrees with them; a junk or empty description on either
side caps the grade at 1; a broad genre alone (action, adventure, puzzle, strategy, simulation, rpg,
party) earns nothing. Three queries have no relevant candidate at all: they are excluded from nDCG
and count only against precision, so the best answer for them is no answer.

## Metric and acceptance bar (frozen before tuning)

Same nDCG@5, gain and discount as [`metric.md`](metric.md); precision = share of returned games
graded 1 or 2; returned games outside the pool are reported as `unjudged` and count as grade 0.

A new policy replaces `text-hybrid` 2.0.0 only if, on the same snapshot, all of these hold:

1. mean nDCG@5 on set 2.0.0 is at least **0.05 higher**;
2. precision on set 2.0.0 is not lower;
3. mean nDCG@5 on set 1.0.0 drops by at most **0.03**;
4. catalogue coverage (games with at least one similar game) does not drop;
5. hard invariants: no game lists itself, at most five results, no duplicates, only catalogue games,
   identical output on a rerun.

## Results

Recorded in `text_report_v2.json` once a candidate is chosen.
