"""`add_rated_games`: score-sorted listing -> only unknown games are ingested, bounded."""

import httpx
from catalog.management.commands.add_rated_games import collect
from catalog.models import Game
from django.test import SimpleTestCase, TestCase
from metacritic.dto import BrowsePage, FetchEvidence, GameDTO, GameIdentityDTO
from metacritic.gateway import MetacriticGateway

from tests.test_catalog_ingest import FakeClock, _evidence, _game, _platform


def _identity(n: int) -> GameIdentityDTO:
    return GameIdentityDTO(f"rated-{n}", f"/game/rated-{n}/", f"Rated {n}")


class Gateway:
    def __init__(self, pages: list[list[int]], failing: set[int] | None = None) -> None:
        self.pages = pages
        self.failing = failing or set()
        self.listings: list[str | None] = []
        self.fetched: list[str] = []

    def iter_browse(
        self, page: int, listing: str | None = None
    ) -> tuple[BrowsePage | None, FetchEvidence]:
        self.listings.append(listing)
        if page > len(self.pages):
            return None, _evidence(outcome="failed", error_code="http_404")
        games = tuple(_identity(n) for n in self.pages[page - 1])
        return BrowsePage(games=games, has_next_page=page < len(self.pages)), _evidence()

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        self.fetched.append(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        number = int(slug.removeprefix("rated-"))
        if number in self.failing:
            return None, _evidence(outcome="failed", error_code="http_503")
        platform = _platform(
            source_platform_id=f"p-{slug}",
            source_game_platform_id=f"r-{slug}",
            critic_path=f"/game/{slug}/critic-reviews/?platform=pc",
            user_path=f"/game/{slug}/user-reviews/?platform=pc",
        )
        game = _game(
            source_game_id=slug,
            canonical_locator=f"/game/{slug}/",
            title=slug,
            platforms=(platform,),
        )
        return game, _evidence()

    def fetch_platform_userscore(self, url: str) -> tuple[None, FetchEvidence]:
        raise AssertionError("not needed")


class CollectTests(TestCase):
    def test_new_games_are_added_up_to_the_limit_from_the_requested_listing(self) -> None:
        gateway = Gateway([[1, 2, 3], [4, 5, 6]])

        counts = collect(gateway, FakeClock(), listing="2025/metascore", limit=4)

        self.assertEqual(counts["added"], 4)
        self.assertEqual(Game.objects.count(), 4)
        self.assertEqual(set(gateway.listings), {"2025/metascore"})
        self.assertEqual(len(gateway.fetched), 4)

    def test_games_already_saved_are_skipped_and_cost_no_detail_request(self) -> None:
        Game.objects.create(
            source_game_id="rated-1", canonical_locator="/game/rated-1/", title="Known"
        )
        gateway = Gateway([[1, 2]])

        counts = collect(gateway, FakeClock(), limit=5)

        self.assertEqual((counts["added"], counts["skipped_known"]), (1, 1))
        self.assertEqual(gateway.fetched, ["https://www.metacritic.com/game/rated-2/"])

    def test_rerunning_adds_nothing_new(self) -> None:
        gateway = Gateway([[1, 2]])
        collect(gateway, FakeClock(), limit=5)

        counts = collect(gateway, FakeClock(), limit=5)

        self.assertEqual((counts["added"], counts["skipped_known"]), (0, 2))

    def test_a_failed_game_is_counted_and_does_not_stop_the_run(self) -> None:
        gateway = Gateway([[1, 2, 3]], failing={2})

        counts = collect(gateway, FakeClock(), limit=5)

        self.assertEqual((counts["added"], counts["failed"]), (2, 1))

    def test_pages_are_bounded_and_a_failing_listing_page_stops_the_scan(self) -> None:
        gateway = Gateway([[1], [2], [3], [4]])
        self.assertEqual(collect(gateway, FakeClock(), limit=10, max_pages=2)["pages"], 2)
        empty = Gateway([])
        counts = collect(empty, FakeClock(), limit=10, max_pages=5)
        self.assertEqual((counts["pages"], counts["failed"], counts["added"]), (1, 1, 0))


class ListingValidationTests(SimpleTestCase):
    def test_only_year_slash_sort_listings_are_accepted_before_any_request(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no request may be made for a bad listing")

        gateway = MetacriticGateway(client=httpx.Client(transport=httpx.MockTransport(handler)))
        for bad in ("", "metascore", "../x/y", "a/b/c", "2025/metascore?x=1", "UPPER/case"):
            with self.subTest(listing=bad), self.assertRaises(ValueError):
                gateway.iter_browse(1, listing=bad)
