from datetime import date

from catalog.models import Game, GamePlatform
from django.test import TestCase


def _game(n: int, title: str) -> Game:
    return Game.objects.create(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=title
    )


def _platform(game: Game, slug: str, name: str, metascore: int | None = None) -> GamePlatform:
    return GamePlatform.objects.create(
        game=game,
        source_platform_id=f"{game.id}-{slug}",
        source_game_platform_id=f"{game.id}-{slug}-rel",
        slug=slug,
        name=name,
        metascore=metascore,
    )


class IndexListTests(TestCase):
    def test_every_game_appears_exactly_once(self) -> None:
        _game(1, "Elden Ring")
        _game(2, "Bayonetta")

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertEqual(content.count("Elden Ring"), 1)
        self.assertEqual(content.count("Bayonetta"), 1)

    def test_search_narrows_results(self) -> None:
        _game(1, "Elden Ring")
        _game(2, "Bayonetta")

        response = self.client.get("/", {"q": "elden"})

        content = response.content.decode()
        self.assertIn("Elden Ring", content)
        self.assertNotIn("Bayonetta", content)

    def test_unknown_search_shows_an_explicit_empty_state(self) -> None:
        _game(1, "Elden Ring")

        response = self.client.get("/", {"q": "no such game anywhere"})

        self.assertContains(response, "No games match")

    def test_platform_filter_narrows_and_reset_restores_the_full_list(self) -> None:
        pc_game = _game(1, "PC Game")
        _platform(pc_game, "pc", "PC", metascore=80)
        ps5_game = _game(2, "PS5 Game")
        _platform(ps5_game, "ps5", "PlayStation 5", metascore=70)

        filtered = self.client.get("/", {"platform": "ps5"})
        self.assertIn("PS5 Game", filtered.content.decode())
        self.assertNotIn("PC Game", filtered.content.decode())

        reset = self.client.get("/")
        reset_content = reset.content.decode()
        self.assertIn("PC Game", reset_content)
        self.assertIn("PS5 Game", reset_content)

    def test_sort_order_matches_asm_15_in_the_rendered_list(self) -> None:
        low = _game(1, "Low Score Game")
        _platform(low, "pc", "PC", metascore=40)
        high = _game(2, "High Score Game")
        _platform(high, "pc", "PC", metascore=95)
        unscored = _game(3, "Unscored Game")
        _platform(unscored, "pc", "PC", metascore=None)

        content = self.client.get("/").content.decode()

        self.assertLess(
            content.index("High Score Game"),
            content.index("Low Score Game"),
        )
        self.assertLess(
            content.index("Low Score Game"),
            content.index("Unscored Game"),
        )

    def test_a_long_title_and_missing_cover_do_not_break_the_response(self) -> None:
        long_title = "A Very Long Title That Keeps Going " * 6  # within the 255-char DB limit
        game = _game(1, long_title)
        _platform(game, "pc", "PC", metascore=50)
        self.assertIsNone(game.cover_url)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(long_title, response.content.decode())


class BackToResultsRoundTripTests(TestCase):
    def test_a_game_link_and_its_back_link_reproduce_the_same_list_url(self) -> None:
        game = _game(1, "Elden Ring")
        _platform(game, "pc", "PC", metascore=90)

        list_response = self.client.get("/", {"q": "elden", "platform": "pc"})
        content = list_response.content.decode()
        expected_query = "q=elden&amp;platform=pc"
        self.assertIn(f"/games/{game.id}/?{expected_query}", content)

        detail_response = self.client.get(f"/games/{game.id}/?q=elden&platform=pc")
        detail_content = detail_response.content.decode()
        self.assertIn(f"/?{expected_query}", detail_content)


class ReleaseSortTests(TestCase):
    def _dated(self) -> None:
        for n, (title, released) in enumerate(
            [("Older Game", date(2024, 5, 1)), ("Newer Game", date(2026, 8, 1))], start=1
        ):
            game = _game(n, title)
            game.release_date = released
            game.save()
            _platform(game, "pc", "PC", metascore=90 - 30 * (n - 1))

    def test_release_sort_orders_newest_first_and_shows_the_date(self) -> None:
        self._dated()

        content = self.client.get("/?sort=release").content.decode()

        self.assertLess(content.index("Newer Game"), content.index("Older Game"))
        self.assertIn("1 Aug 2026", content)
        self.assertIn('<option value="release" selected>', content)

    def test_default_order_is_still_by_score_and_unknown_sort_values_are_ignored(self) -> None:
        self._dated()

        for url in ("/", "/?sort=bogus"):
            content = self.client.get(url).content.decode()
            self.assertLess(content.index("Older Game"), content.index("Newer Game"), url)

    def test_the_sort_survives_the_round_trip_to_a_card_and_back(self) -> None:
        self._dated()
        game = Game.objects.get(title="Newer Game")

        content = self.client.get("/?sort=release&q=Game").content.decode()
        self.assertIn(f"/games/{game.id}/?q=Game&amp;sort=release", content)
        back = self.client.get(f"/games/{game.id}/?q=Game&sort=release").content.decode()
        self.assertIn('href="/?q=Game&amp;sort=release"', back)
