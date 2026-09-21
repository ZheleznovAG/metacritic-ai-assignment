"""Add already-rated games to the catalogue: `python app/manage.py add_rated_games`.

The hourly scheduler only follows the New Releases and "newest first" listings, which are almost
entirely unrated games (93% of the catalogue had no reviews at all). This command walks a Metacritic
browse listing that is sorted by score instead (default `current-year/metascore`, the best games of
the year) and ingests up to `--limit` games that are not saved yet, through the same
`catalog.ingest.ingest_game` path as `ingest_game`. The worker then collects their reviews and
writes summaries as usual, within the free Groq quota. Run it again whenever more games are wanted;
games already in the catalogue are skipped, so it never repeats work.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from metacritic.gateway import ALLOWED_HOST, MetacriticGateway
from processing.clock import Clock, SystemClock

from catalog.ingest import ingest_game
from catalog.models import Game

DEFAULT_LISTING = "current-year/metascore"


def collect(
    gateway: Any,
    clock: Clock,
    *,
    listing: str = DEFAULT_LISTING,
    limit: int = 20,
    max_pages: int = 10,
    pause: float = 0.0,
) -> dict[str, int]:
    counts = {"added": 0, "skipped_known": 0, "failed": 0, "pages": 0}
    for page in range(1, max_pages + 1):
        if counts["added"] >= limit:
            break
        browse, _ = gateway.iter_browse(page, listing=listing)
        counts["pages"] += 1
        if browse is None:
            counts["failed"] += 1
            break
        for identity in browse.games:
            if counts["added"] >= limit:
                break
            if Game.objects.filter(source_game_id=identity.source_game_id).exists():
                counts["skipped_known"] += 1
                continue
            if pause:
                time.sleep(pause)
            result = ingest_game(
                gateway, clock, f"https://{ALLOWED_HOST}{identity.canonical_locator}"
            )
            counts["added" if result.ok else "failed"] += 1
        if not browse.has_next_page:
            break
    return counts


class Command(BaseCommand):
    help = "Ingests games from a score-sorted Metacritic listing that are not saved yet."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--listing",
            default=DEFAULT_LISTING,
            help="`<year>/<sort>` under /browse/game/all/all/, e.g. current-year/metascore, "
            "2025/metascore or all-time/userscore.",
        )
        parser.add_argument("--limit", type=int, default=20, help="Games to add (default 20).")
        parser.add_argument("--max-pages", type=int, default=10, help="Listing pages to scan.")
        parser.add_argument("--pause", type=float, default=1.0, help="Seconds between games.")

    def handle(self, *args: Any, **options: Any) -> None:
        gateway = MetacriticGateway()
        try:
            counts = collect(
                gateway,
                SystemClock(),
                listing=options["listing"],
                limit=options["limit"],
                max_pages=options["max_pages"],
                pause=options["pause"],
            )
        finally:
            gateway.close()
        self.stdout.write(self.style.SUCCESS(" ".join(f"{k}={v}" for k, v in counts.items())))
