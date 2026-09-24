# ADR-0004: Rank games with a foreign or missing description by title and genre

- **Status:** Implemented for the personal service, 2026-09-24, with the owner's explicit acceptance
  of one unmet frozen criterion (below). Not a formal re-run of the `IMP-06`/`SIM-VER-01` gates.
- **Amends:** [ADR-0003](0003-text-hybrid-similarity.md) (`text-hybrid` 2.0.0 → 3.0.0). The fusion,
  model, floor and precompute/read split are unchanged.
- **Requirements/risks:** `SIM-01`, `SIM-02`, `AC-SIM-01/02/03`, `R-SIM-01`.

## Context

About a quarter of the catalogue (264 of 1046 described games in the 1196-game snapshot) carries a
legacy mobile-app description that belongs to another game: a "third person shooter" described as
a slot machine, a "fishing" game as a car-assembly app. Policy 2.0.0 trusted that text, so such
games were matched with each other by the foreign text and pushed into the lists of unrelated
games. The 150 games without a description got no similar games at all.

## Decision

Policy `text-hybrid` 3.0.0 ([`similarity/text.py`](../../app/similarity/text.py)):

1. `description_problem` rejects a description with app-store boilerplate (iPhone, App Store,
   Game Center, "FREE for a limited time", download calls), `?` runs left by stripped emoji, or an
   opening that introduces a differently named game ("Skatpalast offers you Skat...").
2. A game with a usable description is compared only with other such games, exactly as in 2.0.0.
3. Every other game is compared with all games by its label, `title. genre.`, using the same
   embedding + TF-IDF fusion; it no longer gets foreign or no matches.
4. Sharing a genre adds `1.0` to the fused score.
5. Each saved neighbour carries its reasons (`genre`, up to three shared `terms`, `basis`); the
   card shows them and says once when matching used only the title and genre.

The worker embeds two texts per game (`game_embedding.kind`: `label`, `description`) and stores a
per-game input fingerprint in `game_neighbors`, so a description that becomes unusable (which
changes no embedding) still triggers a rebuild (`catalog.0010`).

## Evidence

Protocol: [`text_comparison_v2.md`](../../evals/similarity/text_comparison_v2.md). The new label set
(24 seeded queries, blind pooled grading, identity rule for foreign descriptions) and the acceptance
bar were committed (`561d0c3`) before any candidate was tuned. Report:
[`text_report_v2.json`](../../evals/similarity/text_report_v2.json), same 1196-game snapshot, real
model.

| Method | set 2.0.0 nDCG@5 | precision | set 1.0.0 nDCG@5 | coverage |
|---|---|---|---|---|
| `genre-jaccard` 1.0.0 | 0.382 | 0.472 | 0.150 | - |
| `text-hybrid` 2.0.0 | 0.318 | 0.343 | 0.605 | 1046 |
| `text-hybrid` 3.0.0 | **0.570** | **0.508** | 0.378 | **1196** |

Criteria 1, 2, 4 and 5 hold. **Criterion 3 (set 1.0.0 may drop by at most 0.03) is not met.** Four
of that set's 11 queries have foreign descriptions (SIDE OUT, Tale of Beauty, Cipher Monk, ArmedAbyss)
and were graded, before the identity rule existed, by that foreign text: their "relevant" games are
other slot machines and helicopter apps. 3.0.0 scores 0 on them by design. On the other seven
queries the change is 0.628 → 0.594, most of it one query (Skate Felon) whose grade-2 candidate has a
foreign description. The owner chose to ship 3.0.0 with this disclosed rather than the weaker
variant that met every criterion (embedding consistency gate: set 2.0.0 0.455, 53 games flagged,
most foreign descriptions missed).

Tuning after the freeze: the detector's markers and the genre bonus (0, 0.25, 0.5, 0.75, 1.0, 1.5;
1.0 chosen on a plateau worth +0.04) were chosen on set 2.0.0 itself. The detector was also checked
outside the labels: 39 of 40 randomly sampled flagged descriptions are foreign (the exception is an
authentic description with emoji stripped to `?`).

## Limitations (disclosed, not resolved)

- **One grader, and the same one.** Blind to method, not to the policy's intent; set 2.0.0 rewards
  a shared specific genre, which partly favours the genre bonus (genre Jaccard alone scores 0.382
  there, above 2.0.0).
- **Unjudged results.** 27 of 3.0.0's 120 set-2.0.0 results fall outside the pool and count as 0.
- **Heuristic detector.** Literal markers miss foreign descriptions without boilerplate (for example
  "Tic Tac Toe" text under an unrelated title) and can flag an authentic one. The verdict is not
  shown to readers; only the matching basis is.
- **Label matching is shallow.** A title and one genre say little; games whose titles share a word
  ("Dragon ...") can match on that alone. Genre usually dominates.

## Rollback

Set `POLICY_VERSION` back and restore `rank_neighbors` as the worker's ranking (2.0.0 is still in
`similarity/text.py` as the evaluation baseline); the extra `label` embeddings and fingerprints can
stay unused. The web ignores rows of another `policy_version`, so a rollback shows the empty state
until the worker rebuilds.
