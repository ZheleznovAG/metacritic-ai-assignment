import json
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase
from metacritic.errors import MetacriticParseError
from metacritic.parser import (
    _find_game_record,
    _parse_platform,
    _safe_url,
    parse_game_detail,
    parse_platform_userscore,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metacritic"
DETAIL_URL = "https://www.metacritic.com/game/elden-ring/"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _user_url(slug: str) -> str:
    return f"https://www.metacritic.com/game/elden-ring/user-reviews/?platform={slug}"


def _platform_payload(
    *, related: object, critic_path: object
) -> tuple[list[object], dict[str, object]]:
    payload: list[object] = [None] * 10
    payload[0] = "p1"
    payload[1] = "PC"
    payload[2] = related
    payload[3] = "pc"
    payload[4] = {"url": 6, "score": 7, "normalizedScore": 8, "reviewCount": 9}
    payload[5] = True
    payload[6] = critic_path
    record: dict[str, object] = {
        "id": 0,
        "name": 1,
        "relatedGameId": 2,
        "slug": 3,
        "criticScoreSummary": 4,
        "isLeadPlatform": 5,
    }
    return payload, record


def _two_game_records_payload() -> list[object]:
    # index: 0="game-title", 1="similar-game-slug", 2="elden-ring", 3=[], 4=[]
    payload: list[object] = [
        "game-title",
        "similar-game-slug",
        "elden-ring",
        [],
        [],
        {"type": 0, "slug": 1, "platforms": 3},  # a same-shaped record for a *different* game
        {"type": 0, "slug": 2, "platforms": 4},  # the one actually requested
    ]
    return payload


class ParseGameDetailTests(SimpleTestCase):
    def setUp(self) -> None:
        self.expected = json.loads(_read("elden_ring_expected.json"))
        self.dto = parse_game_detail(_read("elden_ring_detail.min.html"), DETAIL_URL)

    def test_identity_and_scalar_fields_match_the_independent_expected_values(self) -> None:
        expected_game = self.expected["game"]
        self.assertEqual(self.dto.source_game_id, expected_game["source_game_id"])
        self.assertEqual(self.dto.canonical_locator, expected_game["canonical_locator"])
        self.assertEqual(self.dto.title, expected_game["title"])
        self.assertEqual(self.dto.cover_url, expected_game["cover_url"])
        self.assertEqual(self.dto.developer, expected_game["developer"])
        self.assertEqual(self.dto.description, expected_game["description_excerpt"])
        self.assertEqual(self.dto.video_embed_url, expected_game["video_embed_url"])
        self.assertEqual(self.dto.video_content_url, expected_game["video_content_url"])

    def test_all_five_platforms_are_extracted_with_their_own_scores(self) -> None:
        expected_platforms = {p["slug"]: p for p in self.expected["platforms"]}
        self.assertEqual({p.slug for p in self.dto.platforms}, set(expected_platforms))
        for platform in self.dto.platforms:
            expected = expected_platforms[platform.slug]
            self.assertEqual(platform.source_platform_id, expected["source_platform_id"])
            self.assertEqual(platform.source_game_platform_id, expected["source_game_platform_id"])
            self.assertEqual(platform.name, expected["name"])
            self.assertEqual(platform.is_lead_platform, expected["is_lead_platform"])
            self.assertEqual(platform.metascore, expected["metascore"])
            self.assertEqual(platform.critic_reviews_path, expected["critic_reviews_path"])
            self.assertEqual(platform.user_reviews_path, expected["user_reviews_path"])

    def test_natural_nulls_are_preserved_as_none_not_zero(self) -> None:
        by_slug = {p.slug: p for p in self.dto.platforms}
        self.assertIsNone(by_slug["xbox-one"].metascore)
        self.assertIsNone(by_slug["playstation-4"].metascore)

    def test_lead_platform_userscore_comes_from_the_embedded_hero_widget(self) -> None:
        lead = next(p for p in self.dto.platforms if p.is_lead_platform)
        self.assertEqual(lead.slug, "playstation-5")
        self.assertEqual(lead.userscore, Decimal("8.4"))

    def test_non_lead_platforms_have_no_userscore_from_the_detail_page_alone(self) -> None:
        for platform in self.dto.platforms:
            if not platform.is_lead_platform:
                self.assertIsNone(platform.userscore)


class ParseGameDetailFailureTests(SimpleTestCase):
    def test_structurally_corrupted_payload_raises_instead_of_returning_partial_data(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_game_detail(_read("elden_ring_detail_corrupted.min.html"), DETAIL_URL)

    def test_missing_json_ld_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_game_detail("<html><body>no data here</body></html>", DETAIL_URL)

    def test_mismatched_canonical_url_raises(self) -> None:
        # Guards against a silent redirect/misroute serving a different game than requested.
        other_url = "https://www.metacritic.com/game/some-other-game/"
        with self.assertRaises(MetacriticParseError):
            parse_game_detail(_read("elden_ring_detail.min.html"), other_url)


class FindGameRecordTests(SimpleTestCase):
    def test_picks_the_record_matching_the_requested_slug_not_the_first_one(self) -> None:
        payload = _two_game_records_payload()
        record = _find_game_record(payload, "elden-ring")
        slug_index = record["slug"]
        assert isinstance(slug_index, int)
        self.assertEqual(payload[slug_index], "elden-ring")

    def test_no_matching_slug_raises(self) -> None:
        payload = _two_game_records_payload()
        with self.assertRaises(MetacriticParseError):
            _find_game_record(payload, "not-present")


class ParsePlatformFieldTests(SimpleTestCase):
    def test_missing_related_game_id_raises_instead_of_an_empty_placeholder(self) -> None:
        payload, record = _platform_payload(
            related=None, critic_path="/x/critic-reviews/?platform=pc"
        )
        with self.assertRaises(MetacriticParseError):
            _parse_platform(payload, record)

    def test_user_reviews_path_is_not_derived_without_a_known_marker(self) -> None:
        payload, record = _platform_payload(related="99", critic_path="/x/reviews-alt/?platform=pc")
        dto = _parse_platform(payload, record)
        self.assertEqual(dto.critic_reviews_path, "/x/reviews-alt/?platform=pc")
        self.assertIsNone(dto.user_reviews_path)

    def test_user_reviews_path_is_derived_from_a_recognised_critic_path(self) -> None:
        payload, record = _platform_payload(
            related="99", critic_path="/x/critic-reviews/?platform=pc"
        )
        dto = _parse_platform(payload, record)
        self.assertEqual(dto.user_reviews_path, "/x/user-reviews/?platform=pc")


class SafeUrlTests(SimpleTestCase):
    def test_javascript_scheme_is_rejected(self) -> None:
        self.assertIsNone(_safe_url("javascript:alert(1)"))

    def test_data_scheme_is_rejected(self) -> None:
        self.assertIsNone(_safe_url("data:text/html,<script>alert(1)</script>"))

    def test_https_is_accepted(self) -> None:
        self.assertEqual(
            _safe_url("https://example.invalid/x.jpg"), "https://example.invalid/x.jpg"
        )

    def test_non_string_is_rejected(self) -> None:
        self.assertIsNone(_safe_url(123))


class ParsePlatformUserscoreTests(SimpleTestCase):
    def test_reads_each_platforms_own_userscore(self) -> None:
        expected = {
            "pc": Decimal("7.6"),
            "xbox-one": Decimal("7.0"),
            "playstation-4": Decimal("7.5"),
            "xbox-series-x": Decimal("8.0"),
        }
        for slug, score in expected.items():
            fixture = f"elden_ring_user_{slug.replace('-', '_')}.min.html"
            self.assertEqual(parse_platform_userscore(_read(fixture), _user_url(slug)), score)

    def test_missing_widget_raises(self) -> None:
        with self.assertRaises(MetacriticParseError):
            parse_platform_userscore("<html><body>nothing here</body></html>", _user_url("pc"))

    def test_mismatched_platform_page_raises(self) -> None:
        # A page that actually answers for a *different* platform must not be silently accepted
        # as the requested one's score.
        with self.assertRaises(MetacriticParseError):
            parse_platform_userscore(_read("elden_ring_user_pc.min.html"), _user_url("xbox-one"))
