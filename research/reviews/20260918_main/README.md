# Main-scope audit probes, 2026-09-18

Reviewed source: `4109ef17b624afbe977dae33dd13a0ecfdb3836e`.
[Review and requirement mappings](../../../docs/requirements/main_audit_2026_09_18.md).
[Execution observations](observations.json), [verbatim check excerpts and hashes](verification.txt). Current correction statuses belong only
to [action_plan.md](../../../action_plan.md).

`probe.py` reproduces MA-01 (blank review selection), MA-02 (partial platform parser)
and MA-03 (first collection error hidden as Pending). It uses the actual application
and PostgreSQL with controlled source/provider inputs. It never calls live Metacritic
or paid AI. Its assertions confirm historical defects: a correct fix should make the
corresponding assertion fail. It is excluded from application tests and CI gates.

Use a separate Docker project. Run sequentially with other checks against that project:

```powershell
docker compose --env-file .env.app --project-name metacritic-main-audit-20260918 -f compose.yaml -f compose.ci.yaml build web checks
docker compose --env-file .env.app --project-name metacritic-main-audit-20260918 -f compose.yaml -f compose.ci.yaml run --rm checks
docker compose --env-file .env.app --project-name metacritic-main-audit-20260918 -f compose.yaml -f compose.ci.yaml run --rm --volume "${PWD}/research/reviews/20260918_main:/audit:ro" checks python -B /audit/probe.py
docker compose --env-file .env.app --project-name metacritic-main-audit-20260918 -f compose.yaml -f compose.ci.yaml down
```

The probe requires `APP_ENV=test` and a checks database name, creates/destroys Django's
disposable test database and builds static files inside its disposable checks container.
It does not change a production database or invoke background commands.

`observations.json` also holds a dated read-only production snapshot, anonymous browser
checks and four live source-page comparisons. These observations are separate from
deterministic verification; running the probes does not refresh them. Source descriptions,
raw CI logs, credentials, SSH configuration and email addresses are not packaged here.
