"""`backfill_game_metadata`: fills only the three optional fields, from fake fetches."""

from dataclasses import replace
from datetime import date

from catalog.management.commands.backfill_game_metadata import backfill
from catalog.models import Game
from django.test import TestCase
from metacritic.dto import FetchEvidence, GameDTO

from tests.test_catalog_ingest import _evidence, _game


class Gateway:
    def __init__(self, by_locator: dict[str, GameDTO | None]) -> None:
        self.by_locator = by_locator
        self.urls: list[str] = []

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        self.urls.append(url)
        dto = self.by_locator.get(url.removeprefix("https://www.metacritic.com"))
        return dto, _evidence(outcome="succeeded" if dto else "failed")


def _saved(pk: int, **extra: object) -> Game:
    return Game.objects.create(
        id=pk,
        source_game_id=f"bf-{pk}",
        canonical_locator=f"/game/bf-{pk}/",
        title=f"Game {pk}",
        **extra,
    )


class BackfillTests(TestCase):
    def test_missing_fields_are_filled_and_nothing_else_is_created(self) -> None:
        _saved(1)
        dto = replace(
            _game(), release_date=date(2026, 9, 1), publishers=("Pub",), content_rating="T"
        )

        counts = backfill(Gateway({"/game/bf-1/": dto}))

        game = Game.objects.get(pk=1)
        self.assertEqual(
            (game.release_date, game.publishers, game.content_rating),
            (date(2026, 9, 1), ["Pub"], "T"),
        )
        self.assertEqual(counts, {"updated": 1, "unchanged": 0, "failed": 0})

    def test_games_that_already_have_a_date_are_not_fetched(self) -> None:
        _saved(1, release_date=date(2020, 1, 1))
        gateway = Gateway({})

        backfill(gateway)

        self.assertEqual(gateway.urls, [])

    def test_a_page_without_metadata_and_a_failed_fetch_change_nothing(self) -> None:
        _saved(1, publishers=["Kept"])
        _saved(2)

        counts = backfill(Gateway({"/game/bf-1/": _game(), "/game/bf-2/": None}))

        self.assertEqual(counts, {"updated": 0, "unchanged": 1, "failed": 1})
        self.assertEqual(Game.objects.get(pk=1).publishers, ["Kept"])
        self.assertIsNone(Game.objects.get(pk=1).release_date)

    def test_limit_bounds_the_number_of_requests_and_order_is_by_id(self) -> None:
        for pk in (3, 1, 2):
            _saved(pk)
        gateway = Gateway({})

        backfill(gateway, limit=2)

        self.assertEqual(
            gateway.urls,
            ["https://www.metacritic.com/game/bf-1/", "https://www.metacritic.com/game/bf-2/"],
        )
