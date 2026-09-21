from datetime import date

from catalog.models import Game, GamePlatform
from catalog.queries import list_games, list_platform_options
from django.test import TestCase


def _game(n: int, title: str, developer: str | None = None) -> Game:
    return Game.objects.create(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=title, developer=developer
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


class SearchTests(TestCase):
    def test_case_insensitive_substring_match(self) -> None:
        _game(1, "Elden Ring")
        _game(2, "Bayonetta")
        results = list_games(query="ELDEN")
        self.assertEqual([item.title for item in results], ["Elden Ring"])

    def test_unknown_query_returns_an_empty_result(self) -> None:
        _game(1, "Elden Ring")
        self.assertEqual(list_games(query="no such game"), [])

    def test_empty_query_returns_everything(self) -> None:
        _game(1, "Elden Ring")
        _game(2, "Bayonetta")
        self.assertEqual(len(list_games(query="")), 2)


class PlatformFilterTests(TestCase):
    def test_filter_excludes_games_without_that_platform(self) -> None:
        pc_only = _game(1, "PC Only")
        _platform(pc_only, "pc", "PC", metascore=80)
        both = _game(2, "Both Platforms")
        _platform(both, "pc", "PC", metascore=70)
        _platform(both, "ps5", "PlayStation 5", metascore=90)

        results = list_games(platform="ps5")

        self.assertEqual([item.title for item in results], ["Both Platforms"])

    def test_reset_with_no_platform_restores_the_full_set(self) -> None:
        game1 = _game(1, "Game One")
        _platform(game1, "pc", "PC", metascore=80)
        game2 = _game(2, "Game Two")
        _platform(game2, "ps5", "PlayStation 5", metascore=70)

        self.assertEqual(len(list_games(platform=None)), 2)

    def test_filtered_metascore_is_the_max_among_matched_platforms_only(self) -> None:
        # ASM-15: with a filter, the displayed score is the max among the MATCHED platform(s),
        # not the game's overall max across every platform it has.
        game = _game(1, "Multi Platform Game")
        _platform(game, "pc", "PC", metascore=95)
        _platform(game, "ps5", "PlayStation 5", metascore=60)

        filtered = list_games(platform="ps5")
        unfiltered = list_games()

        self.assertEqual(filtered[0].metascore, 60)
        self.assertEqual(unfiltered[0].metascore, 95)


class SortOrderTests(TestCase):
    def test_scored_games_sort_descending(self) -> None:
        low = _game(1, "Low Score")
        _platform(low, "pc", "PC", metascore=50)
        high = _game(2, "High Score")
        _platform(high, "pc", "PC", metascore=90)

        results = list_games()

        self.assertEqual([item.title for item in results], ["High Score", "Low Score"])

    def test_games_with_no_score_sort_after_scored_games(self) -> None:
        scored = _game(1, "Scored")
        _platform(scored, "pc", "PC", metascore=10)
        unscored = _game(2, "Unscored")
        _platform(unscored, "pc", "PC", metascore=None)

        results = list_games()

        self.assertEqual([item.title for item in results], ["Scored", "Unscored"])

    def test_a_game_with_no_platforms_at_all_sorts_after_scored_games(self) -> None:
        scored = _game(1, "Scored")
        _platform(scored, "pc", "PC", metascore=10)
        _game(2, "No Platforms")

        results = list_games()

        self.assertEqual([item.title for item in results], ["Scored", "No Platforms"])

    def test_ties_break_by_title_case_insensitively(self) -> None:
        b_game = _game(1, "banana")
        _platform(b_game, "pc", "PC", metascore=80)
        a_game = _game(2, "Apple")
        _platform(a_game, "pc", "PC", metascore=80)

        results = list_games()

        self.assertEqual([item.title for item in results], ["Apple", "banana"])

    def test_multi_platform_game_uses_its_max_score_when_unfiltered(self) -> None:
        game = _game(1, "Multi")
        _platform(game, "pc", "PC", metascore=40)
        _platform(game, "ps5", "PlayStation 5", metascore=85)

        results = list_games()

        self.assertEqual(results[0].metascore, 85)


class ReleaseDateSortTests(TestCase):
    def test_release_sort_is_newest_first_with_undated_games_last_then_by_title(self) -> None:
        old = _game(1, "Old")
        old.release_date = date(2020, 1, 1)
        old.save()
        new = _game(2, "New")
        new.release_date = date(2026, 9, 1)
        new.save()
        _game(3, "Zed undated")
        _game(4, "Alpha undated")

        titles = [item.title for item in list_games(sort="release")]

        self.assertEqual(titles, ["New", "Old", "Alpha undated", "Zed undated"])

    def test_the_default_sort_is_unchanged_and_items_carry_the_date(self) -> None:
        game = _game(1, "Dated")
        game.release_date = date(2026, 1, 2)
        game.save()
        _platform(game, "pc", "PC", metascore=80)

        (item,) = list_games()

        self.assertEqual((item.metascore, item.release_date), (80, date(2026, 1, 2)))

    def test_release_sort_combines_with_search_and_platform_filter(self) -> None:
        a = _game(1, "Quest A")
        a.release_date = date(2025, 1, 1)
        a.save()
        b = _game(2, "Quest B")
        b.release_date = date(2026, 1, 1)
        b.save()
        _platform(a, "pc", "PC")
        _platform(b, "pc", "PC")

        titles = [i.title for i in list_games(query="quest", platform="pc", sort="release")]

        self.assertEqual(titles, ["Quest B", "Quest A"])


class CombinedSearchAndFilterTests(TestCase):
    def test_search_and_filter_compose(self) -> None:
        match = _game(1, "Elden Ring")
        _platform(match, "pc", "PC", metascore=95)
        wrong_platform = _game(2, "Elden Clone")
        _platform(wrong_platform, "ps5", "PlayStation 5", metascore=50)
        wrong_title = _game(3, "Bayonetta")
        _platform(wrong_title, "pc", "PC", metascore=90)

        results = list_games(query="elden", platform="pc")

        self.assertEqual([item.title for item in results], ["Elden Ring"])


class ListPlatformOptionsTests(TestCase):
    def test_returns_distinct_platforms_ordered_by_name(self) -> None:
        game1 = _game(1, "Game One")
        _platform(game1, "pc", "PC")
        game2 = _game(2, "Game Two")
        _platform(game2, "pc", "PC")
        _platform(game2, "ps5", "PlayStation 5")

        options = list_platform_options()

        self.assertEqual(
            [(o.slug, o.name) for o in options], [("pc", "PC"), ("ps5", "PlayStation 5")]
        )
