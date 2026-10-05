# FIN-DOCS documentation/source audit

This dated standard-library audit checks the current documents and ADRs against
local paths and AST-read runtime constants. It is independent of the authored
claims and makes no remote-availability or substantive quality determination.

```powershell
.\.venv-app\Scripts\python.exe -B research/reviews/20261005_fin_docs/check.py
.\.venv-app\Scripts\python.exe -B research/planning/check_plan.py
.\.venv-app\Scripts\python.exe -B -m unittest discover -s research/planning -p "test_*.py"
```

The audit reports its document/link counts, unique ADR identities and policy bindings,
checks that application/frozen evaluation files did not change from `3270226`, and
includes negative controls for path, identity and constant mismatches. It checks
local path existence only; fragments and remote URLs require separate review.
Original historical findings and gate decisions are retained, not rerun at HEAD.

Results: [source/link audit](../../../docs/evidence/fin-docs/audit.json),
[planning verification](../../../docs/evidence/fin-docs/planning.txt).
Task/evidence review: [FIN-DOCS](../../../docs/requirements/fin_docs_review.md).
