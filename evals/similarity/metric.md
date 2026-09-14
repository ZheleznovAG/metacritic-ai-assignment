# SIM-EVAL-01 similarity oracle 1.0.0

Task `SIM-EVAL-01`; `SIM-01–SIM-03`, `AC-SIM-01/03`, `ASM-20/21`, `R-SIM-01`.
Owner acceptance and current task status belong only to
[`action_plan.md`](../../action_plan.md). These artifacts fix the proposed bar
before `IMP-06` compares any method.

## Examples and labels

[`cases.json`](cases.json) contains 14 independent synthetic scenarios with 52
case-local saved game records. Names and metadata are project-authored, not claims
about real games. Each scenario has its own database; internal IDs are its only
identity keys. Every candidate has a grade and a short reason written before
ranking code. The ranker receives immutable catalog records and the query ID;
it never receives the judgments or case name.

| Grade | Meaning | Examples |
|---|---|---|
| 2 | Obvious close relation in the known gameplay genre | Another action RPG, platformer, racer, puzzle or turn-based strategy game |
| 1 | Plausible broader relation, weaker than grade 2 | Shared role-playing or strategy category with a different combat/time structure |
| 0 | Obvious non-match, or no affirmative relation in known metadata | Shared platform alone, same studio across unrelated genres, title collision, missing features |

Nine cases contain relevant candidates; five require an empty result. Coverage:
several genre families, broader versus close matches, sparse metadata, platform
and developer traps, equal titles with distinct IDs, Unicode titles, case/space
normalization, more than five equivalent peers, only-self, empty database, missing
query, and all features absent. Equivalent peers have equal grades; labels do not
prescribe a title/ID tie-break or a numerical similarity formula.

## Metric and acceptance bar

For each case with any positive grade, compute `nDCG@5`:

`DCG@5 = sum((2^grade - 1) / log2(rank + 1))`, with rank starting at 1.

The denominator is the DCG of the best possible five judged candidates in that
case, or all positive candidates when fewer than five exist. Missing returned
positions contribute zero. This measures both ordering and missed useful results.
A duplicate ID earns gain only once; unknown IDs earn zero. No result can obtain
credit from the current game or from missing judgments.

Acceptance requires **all** of:

- Macro mean `nDCG@5 >= 0.90` over the nine positive cases, weighted equally.
- Each positive case `nDCG@5 >= 0.80`, so the mean cannot hide a failed genre family.
- Every hard invariant passes in every scenario and every tested input order.

Cases without positive grades have `nDCG = n/a`; they do not inflate the mean.
Their expected empty result is enforced by the hard invariants. Returning no
results everywhere fails all nine positive cases. There is no requirement to
fill five slots with unrelated games.

Thresholds are design choices proposed for owner approval, not measurements of
user satisfaction. No method was run to select these numbers. If no candidate
passes, improve the method or seek an explicit, versioned oracle revision;
do not alter labels or thresholds to match its output.

## Hard invariants

| ID | Required behavior |
|---|---|
| `INV-VALID-RESULT` | Return a list/tuple of integer saved IDs without an exception; `bool` is not an ID |
| `INV-CAP` | Return at most five results |
| `INV-SAVED` | Every returned ID belongs to this case's saved database |
| `INV-NO-SELF` | Do not return the requested game |
| `INV-UNIQUE` | Do not return an ID twice; equal titles do not merge distinct IDs |
| `INV-NONMATCH` | Do not recommend any of the explicitly judged grade-0 examples |
| `INV-DETERMINISTIC` | Exact ordered IDs repeat for unchanged data, including input-order changes |
| `INV-QUERY` | Return no results when the requested ID is absent |

The evaluator calls each policy with the original catalog twice, then reversed,
rotated and ID-sorted order. All hard checks apply to all five calls; the case
uses the lowest observed nDCG. This finite probe detects ordinary order-sensitive
or stateful implementations; application tests in `SIM-VER-01` must additionally
check the production query and rendering path. Frozen dataclasses/tuples make
ordinary mutation of the provided catalog fail explicitly.

## Reproduction and limits

```powershell
.\.venv-app\Scripts\python.exe -B evals/similarity/score_similarity.py --verify
.\.venv-app\Scripts\python.exe -B -m unittest discover -s evals/similarity -p "test_*.py" -v
```

[`manifest.json`](manifest.json) pins the dataset, this metric, contract and
evaluator by byte hashes. The evaluator's tests include hand-calculated DCG and
deliberately defective outputs; their reference answer reads judgments only as
a test double, and is never a candidate ranking policy.

This is a small synthetic acceptance set. It verifies clear metadata relations
and stated exclusions; it does not prove real-world recommendation satisfaction,
semantic matching without shared vocabulary, personalized taste or production
capacity. No release method is selected here. `IMP-06` compares the design
candidate with a simpler baseline on the accepted immutable oracle;
`SIM-VER-01` owns saved-data integration, ID navigation and public evidence.
