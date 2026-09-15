"""HRD-05 operator diagnostics: `python scripts/diagnose.py --run <id> | --game <id> |
--job review|summary <id> | --backlog`. Read-only (runs under `WEB_DB_USER`, SELECT-only);
prints one JSON object per invocation for scripting/piping, no interactive UI required.
"""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from processing import diagnostics
from processing.clock import SystemClock


class Command(BaseCommand):
    help = "Prints diagnostics for one run/game/job by ID, or the current pipeline backlog."

    def add_arguments(self, parser: CommandParser) -> None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--run", type=int, metavar="RUN_ID")
        group.add_argument("--game", type=int, metavar="GAME_ID")
        group.add_argument("--job", nargs=2, metavar=("KIND", "JOB_ID"))
        group.add_argument("--backlog", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        result: dict[str, Any] | None
        if options["run"] is not None:
            result = diagnostics.run_diagnostics(options["run"])
            not_found = f"no run with id {options['run']}"
        elif options["game"] is not None:
            result = diagnostics.game_diagnostics(options["game"])
            not_found = f"no game with id {options['game']}"
        elif options["job"] is not None:
            kind, raw_job_id = options["job"]
            try:
                job_id = int(raw_job_id)
            except ValueError as error:
                raise CommandError(f"job id must be an integer, got {raw_job_id!r}") from error
            try:
                result = diagnostics.job_diagnostics(kind, job_id)
            except ValueError as error:
                raise CommandError(str(error)) from error
            not_found = f"no {kind} job with id {job_id}"
        else:
            result = diagnostics.backlog_diagnostics(SystemClock())
            not_found = None

        if result is None:
            raise CommandError(not_found or "not found")
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
