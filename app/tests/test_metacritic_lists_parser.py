import json
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase
from metacritic.errors import MetacriticParseError
from metacritic.parser import parse_browse_page, parse_new_releases

FIXTURES = Path(__file__).parent / "fixtures" / "metacritic"
NEW_RELEASES_URL = "https://www.metacritic.com/game/"
BROWSE_BASE = "https://www.metacritic.com/browse/game/all/all/all-time/new/"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _expected() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(_read("lists_expected.json"))
    return result


class ParseNewReleasesTests(SimpleTestCase):
    def setUp(self) -> None:
        self.expected = _expected()["new_releases"]["games"]
        self.games = parse_new_releases(_read("new_releases.min.html"), NEW_RELEASES_URL)

    def test_returns_all_twenty_cards_in_source_order(self) -> None:
        self.assertEqual(len(self.games), 20)
        for game, expected in zip(self.games, self.expected, strict=True):
            self.assertEqual(game.source_game_id, expected["source_game_id"])
            self.assertEqual(game.title, expected["title"])
            self.assertEqual(game.canonical_locator, f"/game/{expected['slug']}/")

    def test_mismatched_canonical_url_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_new_releases(_read("new_releases.min.html"), "https://www.metacritic.com/other/")

    def test_missing_section_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_new_releases(
                '<html><head><link rel="canonical" href="https://www.metacritic.com/game/">'
                "</head><body></body></html>",
                NEW_RELEASES_URL,
            )


class ParseBrowsePageTests(SimpleTestCase):
    def test_page_one_has_a_next_page(self) -> None:
        expected = _expected()["browse_page_1"]
        url = f"{BROWSE_BASE}?page=1"
        page = parse_browse_page(_read("browse_page_1.min.html"), url)
        self.assertTrue(page.has_next_page)
        self.assertEqual(len(page.games), len(expected["games"]))
        for game, exp in zip(page.games, expected["games"], strict=True):
            self.assertEqual(game.source_game_id, exp["source_game_id"])
            self.assertEqual(game.canonical_locator, f"/game/{exp['slug']}/")

    def test_page_two_does_not_overlap_page_one_in_this_snapshot(self) -> None:
        page1 = parse_browse_page(_read("browse_page_1.min.html"), f"{BROWSE_BASE}?page=1")
        page2 = parse_browse_page(_read("browse_page_2.min.html"), f"{BROWSE_BASE}?page=2")
        ids1 = {g.source_game_id for g in page1.games}
        ids2 = {g.source_game_id for g in page2.games}
        self.assertEqual(ids1 & ids2, set())

    def test_last_page_has_no_next_page_real_disabled_marker(self) -> None:
        url = f"{BROWSE_BASE}?page=7429"
        page = parse_browse_page(_read("browse_page_last.min.html"), url)
        self.assertFalse(page.has_next_page)
        self.assertGreater(len(page.games), 0)

    def test_same_listing_different_page_number_is_not_a_canonical_mismatch(self) -> None:
        # Confirmed live on real pages 1, 2 and 7429: every SEE ALL page's canonical is the same
        # bare listing URL regardless of page number, so page number cannot be verified this way
        # (unlike game-detail/platform pages) — a wrong/duplicate page is instead caught safely
        # by this module's identity-based dedup, not by canonical matching.
        page = parse_browse_page(_read("browse_page_1.min.html"), f"{BROWSE_BASE}?page=2")
        self.assertGreater(len(page.games), 0)

    def test_a_genuinely_unrelated_page_is_rejected(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_browse_page(_read("browse_page_1.min.html"), "https://www.metacritic.com/other/")

    def test_missing_pagination_control_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_browse_page(
                f'<html><head><link rel="canonical" href="{BROWSE_BASE}"></head>'
                "<body></body></html>",
                f"{BROWSE_BASE}?page=1",
            )
