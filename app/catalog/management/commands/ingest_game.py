"""IMP-02 one-off proof run: `python scripts/ingest_game.py <detail url>` (see that wrapper for
the required database role). This is not the future scheduler/worker entry point (`IMP-03`).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from metacritic.gateway import MetacriticGateway
from processing.clock import SystemClock

from catalog.ingest import ingest_game


class Command(BaseCommand):
    help = "Fetch one Metacritic game and upsert it (identity, platforms, provenance, jobs)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("url", help="https://www.metacritic.com/game/<slug>/")

    def handle(self, *args: Any, **options: Any) -> None:
        url = options["url"]
        gateway = MetacriticGateway()
        try:
            result = ingest_game(gateway, SystemClock(), url)
        finally:
            gateway.close()

        if not result.ok:
            self.stderr.write(
                self.style.ERROR(
                    f"Ingest failed: fetch={result.fetch_outcome} error={result.error}"
                )
            )
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                f"game_id={result.game_id} created={result.game_created} "
                f"platforms_created={result.platforms_created} "
                f"platforms_updated={result.platforms_updated} "
                f"jobs_created={result.jobs_created} "
                f"candidate_state={result.candidate_state}"
            )
        )
