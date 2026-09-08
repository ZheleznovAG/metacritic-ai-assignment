# Metacritic AI Assignment

Take-home assignment for the AI Automation Engineer position.

The implementation baseline is established. Application source, CI and a public application are not implemented yet; stage/task status is tracked in [action_plan.md](action_plan.md), with task scope and estimates in [implementation_plan.md](implementation_plan.md).

- [Assignment](assignment.md), [requirements and acceptance](docs/requirements/acceptance.md).
- [Architecture](docs/decisions/0001-minimal-stack-and-architecture.md), [data and processing contracts](docs/design.md).
- [Published AI baseline](evals/reviews/baseline/README.md): saved synthetic inputs/outputs and original scoring, independently inspectable without another API call.
- [PLN-02 review and verification](docs/requirements/pln_02_review.md): contract corrections, PostgreSQL probe and remaining implementation limitations.
- [G3 planning review](docs/requirements/g3_review.md): coverage, dependency audit, workload/reserve and explicit limitations. Next priority: the IMP-01 reproducible scaffold and early deploy.

Offline evidence checks from the repository root with Python 3.12 or later (standard library only; no API key or `.env` needed):

```powershell
python -B evals/reviews/score_run.py evals/reviews/baseline/run.json --verify
python -B -m unittest discover -s evals/reviews -p "test_*.py"
python -B research/planning/check_plan.py
python -B -m unittest discover -s research/planning -p "test_*.py"
```

These commands verify research evidence and the planning baseline, not a working application. Token-budget and optional live checks are documented separately in [evals/reviews](evals/reviews/README.md).
