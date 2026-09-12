import json
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase
from metacritic.errors import MetacriticParseError
from metacritic.parser import parse_review_page

FIXTURES = Path(__file__).parent / "fixtures" / "metacritic"
GAME_SLUG = "bayonetta"
PLATFORM_SLUG = "xbox-360"


def _read(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


def _expected() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(_read("review_pages_expected"))
    return result


class ParseReviewPageTests(SimpleTestCase):
    def setUp(self) -> None:
        self.expected = _expected()

    def _assert_matches(self, fixture: str, audience: str) -> None:
        expected = self.expected[fixture]
        page = parse_review_page(_read(fixture), audience, GAME_SLUG, PLATFORM_SLUG)
        self.assertEqual(page.reported_total, expected["reported_total"])
        self.assertEqual(len(page.items), expected["item_count"])
        self.assertEqual(page.next_cursor, expected["next_cursor"])
        for item, key in ((page.items[0], "first"), (page.items[-1], "last")):
            oracle = expected[key]
            self.assertEqual(item.source_review_id, oracle["source_review_id"])
            self.assertEqual(item.author_or_source_label, oracle["author_or_source_label"])
            self.assertEqual(item.score_label, oracle["score_label"])
            self.assertEqual(item.date_label, oracle["date_label"])
            self.assertEqual(item.text, oracle["text"])

    def test_critic_first_page_matches_independent_expected_values(self) -> None:
        self._assert_matches("review_page_critic_bayonetta_xbox360_p0", "critic")

    def test_critic_second_page_matches_independent_expected_values(self) -> None:
        self._assert_matches("review_page_critic_bayonetta_xbox360_p1", "critic")

    def test_critic_last_page_has_no_next_cursor(self) -> None:
        self._assert_matches("review_page_critic_bayonetta_xbox360_last", "critic")
        page = parse_review_page(
            _read("review_page_critic_bayonetta_xbox360_last"), "critic", GAME_SLUG, PLATFORM_SLUG
        )
        self.assertIsNone(page.next_cursor)

    def test_user_first_page_matches_independent_expected_values(self) -> None:
        self._assert_matches("review_page_user_bayonetta_xbox360_p0", "user")

    def test_user_second_page_matches_independent_expected_values(self) -> None:
        self._assert_matches("review_page_user_bayonetta_xbox360_p1", "user")

    def test_user_last_page_has_no_next_cursor(self) -> None:
        self._assert_matches("review_page_user_bayonetta_xbox360_last", "user")
        page = parse_review_page(
            _read("review_page_user_bayonetta_xbox360_last"), "user", GAME_SLUG, PLATFORM_SLUG
        )
        self.assertIsNone(page.next_cursor)

    def test_critic_reviews_have_no_stable_id_and_no_date_in_this_snapshot(self) -> None:
        # A real, natural fact about this route: fall back to publicationSlug identity, and the
        # source genuinely never populated a date for these older critic reviews.
        page = parse_review_page(
            _read("review_page_critic_bayonetta_xbox360_p0"), "critic", GAME_SLUG, PLATFORM_SLUG
        )
        for item in page.items:
            self.assertIsNone(item.source_review_id)
            self.assertIsNone(item.date_label)
            self.assertIsNotNone(item.author_or_source_label)

    def test_user_reviews_have_a_stable_id_and_a_date(self) -> None:
        page = parse_review_page(
            _read("review_page_user_bayonetta_xbox360_p0"), "user", GAME_SLUG, PLATFORM_SLUG
        )
        for item in page.items:
            self.assertIsNotNone(item.source_review_id)
            self.assertIsNotNone(item.date_label)

    def test_mismatched_game_slug_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_review_page(
                _read("review_page_critic_bayonetta_xbox360_p0"),
                "critic",
                "other-game",
                PLATFORM_SLUG,
            )

    def test_mismatched_platform_slug_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_review_page(
                _read("review_page_critic_bayonetta_xbox360_p0"),
                "critic",
                GAME_SLUG,
                "other-platform",
            )

    def test_mismatched_audience_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_review_page(
                _read("review_page_critic_bayonetta_xbox360_p0"), "user", GAME_SLUG, PLATFORM_SLUG
            )

    def test_missing_data_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_review_page(
                json.dumps({"links": {"self": {"href": "x"}}}), "critic", GAME_SLUG, PLATFORM_SLUG
            )

    def test_missing_links_self_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_review_page(
                json.dumps({"data": {"totalResults": 0, "items": []}, "links": {}}),
                "critic",
                GAME_SLUG,
                PLATFORM_SLUG,
            )

    def test_not_valid_json_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_review_page("not json", "critic", GAME_SLUG, PLATFORM_SLUG)

    def test_item_missing_quote_raises(self) -> None:
        expected_path = (
            "/reviews/metacritic/critic/games/bayonetta/platform/xbox-360/web?offset=0&limit=10"
        )
        body = json.dumps(
            {
                "data": {"totalResults": 1, "items": [{"score": 80}]},
                "links": {
                    "self": {"href": f"https://backend.metacritic.com{expected_path}"},
                    "next": {"href": None},
                },
            }
        )
        with self.assertRaises(MetacriticParseError):
            parse_review_page(body, "critic", GAME_SLUG, PLATFORM_SLUG)
