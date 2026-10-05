# FIN-ARCH source inspection

Run from the repository root with Python 3.12; neither tool imports Django or
connects to the database/providers:

```powershell
.\.venv-app\Scripts\python.exe research/reviews/20261005_fin_arch/inventory.py .artifacts/fin-arch-after.json
.\.venv-app\Scripts\python.exe research/reviews/20261005_fin_arch/preservation.py
```

`inventory.py` reads every first-party production package (tests/migrations
excluded), including imports inside functions. It records file-backed package
edges, simple directed cycles (rotation-normalized), function lengths and counts
of `if`/`for`/`while`/exception-handler/conditional-expression AST nodes. These
counts describe hotspots; they are not cyclomatic complexity or a quality score.
`core` edges are omitted, matching the independent application fitness test.

`preservation.py --baseline 9b82da0` compares the moved dispatcher function and
worker command class to the pre-FIN-ARCH source. The sole command alias rename
`dispatch`→`jobs` is normalized. It also compares the collector's complete commit
transaction AST and final return; source locations/formatting are ignored.
An assertion failure means the claimed preservation needs review.

The before inventory was executed on `9b82da0` before edits; both frozen inventories
and source-preservation output are saved under `docs/evidence/fin-arch/`. These
dated probes are evidence, not CI gates. The application architecture, fairness,
collection/summary transaction and orchestration tests run in the ordinary
container/CI suite. [Review](../../../docs/requirements/fin_arch_review.md) maps
exit criteria; [action_plan.md](../../../action_plan.md) owns current status.
