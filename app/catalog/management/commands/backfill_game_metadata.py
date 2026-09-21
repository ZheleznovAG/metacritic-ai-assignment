"""One-off backfill of `release_date`, `publishers` and `content_rating` for games saved before
those fields existed: `python app/manage.py backfill_game_metadata [--limit N] [--pause S]`.

It fetches each missing game's detail page once (no platform score pages, no review or summary
jobs, no daily candidate) and merges only the three optional fields, never overwriting a saved
value with an empty one. Games refresh these fields on their own whenever the scheduler fetches
them again; this command only shortens the wait. Safe to interrupt and to re-run: it selects the
games that still lack a release date.
"""

import time
from typing import Any, Protocol

from django.core.management.base import BaseCommand, CommandParser
from metacritic.dto import FetchEvidence, GameDTO
from metacritic.gateway import ALLOWED_HOST, MetacriticGateway

from catalog.models import Game

DEFAULT_PAUSE_SECONDS = 1.0


class GameFetcher(Protocol):
    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]: ...


def backfill(
    gateway: GameFetcher, *, limit: int | None = None, pause: float = 0.0
) -> dict[str, int]:
    counts = {"updated": 0, "unchanged": 0, "failed": 0}
    games = Game.objects.filter(release_date__isnull=True).order_by("id")
    if limit is not None:
        games = games[:limit]
    for index, game in enumerate(games):
        if index and pause:
            time.sleep(pause)
        dto, _ = gateway.fetch_game(f"https://{ALLOWED_HOST}{game.canonical_locator}")
        if dto is None:
            counts["failed"] += 1
            continue
        fields = []
        if dto.release_date is not None:
            game.release_date = dto.release_date
            fields.append("release_date")
        if dto.publishers:
            game.publishers = list(dto.publishers)
            fields.append("publishers")
        if dto.content_rating:
            game.content_rating = dto.content_rating
            fields.append("content_rating")
        if fields:
            game.save(update_fields=[*fields, "updated_at"])
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    return counts


class Command(BaseCommand):
    help = "Backfills release date, publishers and content rating for games that lack them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Handle at most N games.")
        parser.add_argument(
            "--pause", type=float, default=DEFAULT_PAUSE_SECONDS, help="Seconds between requests."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        gateway = MetacriticGateway()
        try:
            counts = backfill(gateway, limit=options["limit"], pause=options["pause"])
        finally:
            gateway.close()
        self.stdout.write(self.style.SUCCESS(" ".join(f"{k}={v}" for k, v in counts.items())))
