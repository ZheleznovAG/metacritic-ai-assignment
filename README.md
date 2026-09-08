# Metacritic AI Assignment

Take-home assignment for the AI Automation Engineer position.

The repository is completing its implementation baseline. Application source, CI and a public application are not implemented yet; stage/task status is tracked in [action_plan.md](action_plan.md).

- [Assignment](assignment.md), [requirements and acceptance](docs/requirements/acceptance.md).
- [Architecture](docs/decisions/0001-minimal-stack-and-architecture.md), [data and processing contracts](docs/design.md).
- [Published AI baseline](evals/reviews/baseline/README.md): saved synthetic inputs/outputs and original scoring, independently inspectable without another API call.
- [PLN-02 review and verification](docs/requirements/pln_02_review.md): contract corrections, PostgreSQL probe and remaining implementation limitations.

Offline evidence checks from the repository root with Python 3.12 or later (standard library only; no API key or `.env` needed):

```powershell
python -B evals/reviews/score_run.py evals/reviews/baseline/run.json --verify
python -B -m unittest discover -s evals/reviews -p "test_*.py"
```

These commands verify research evidence, not a working application. Token-budget and optional live checks are documented separately in [evals/reviews](evals/reviews/README.md).
