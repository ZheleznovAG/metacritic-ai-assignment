"""IMP-03 real scheduler entry point: `python scripts/run_scheduler.py [--once]`.

`docs/design.md` requires checking the current UTC slot at least once a minute; the continuous
mode here checks well inside that bound. `--once` runs a single tick and exits (used by tests and
for a single scripted invocation, e.g. from an external cron as an alternative to the loop).
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from metacritic.gateway import MetacriticGateway

from processing.clock import SystemClock
from processing.scheduler import TickResult, run_tick

POLL_INTERVAL_SECONDS = 20


class Command(BaseCommand):
    help = "Checks the current UTC hour slot and processes one batch if due."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true", help="Run a single tick and exit.")

    def handle(self, *args: Any, **options: Any) -> None:
        gateway = MetacriticGateway()
        clock = SystemClock()
        try:
            if options["once"]:
                self._tick(gateway, clock)
                return
            while True:
                self._tick(gateway, clock)
                time.sleep(POLL_INTERVAL_SECONDS)
        finally:
            gateway.close()

    def _tick(self, gateway: MetacriticGateway, clock: SystemClock) -> TickResult:
        result = run_tick(gateway, clock)
        run = result.run
        self.stdout.write(
            self.style.SUCCESS(
                f"run_id={run.id} trigger_key={run.trigger_key} outcome={result.outcome} "
                f"selected={run.selected_count} processed={run.processed_count} "
                f"failed={run.failed_count}"
            )
        )
        return result
