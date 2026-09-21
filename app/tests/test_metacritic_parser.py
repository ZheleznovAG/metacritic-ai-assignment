import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.test import SimpleTestCase
from metacritic.errors import MetacriticParseError
from metacritic.parser import (
    _extract_content_rating,
    _extract_publishers,
    _extract_release_date,
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


class LiveContractStrayUserScoreWidgetTests(SimpleTestCase):
    """2026-09-14 live finding on IMP-03 revalidation: a brand-new game with zero user ratings
    renders a *second*, unrelated widget elsewhere on the page whose title attribute literally
    reads "User score null out of 10" -- a real site templating artifact, not the natural "TBD"
    label the actual hero widget uses. A whole-page scan for any "User score ... out of 10"
    title can match this stray widget (or an individual review card's own score) instead of the
    real hero/score-card widget, either raising on the literal text "null" or silently returning
    the wrong platform's score. Extraction must stay scoped to the hero/score-card container."""

    def test_a_stray_null_titled_widget_outside_the_hero_container_does_not_raise(self) -> None:
        dto = parse_game_detail(
            _read("bioeden_detail_tbd_userscore.min.html"),
            "https://www.metacritic.com/game/bioeden/",
        )
        lead = next(p for p in dto.platforms if p.is_lead_platform)
        self.assertEqual(lead.slug, "pc")
        self.assertIsNone(lead.userscore)

    def test_an_individual_review_cards_own_score_is_not_mistaken_for_the_aggregate(self) -> None:
        result = parse_platform_userscore(
            _read("shatterverse_user_xbox_series_x_tbd.min.html"),
            "https://www.metacritic.com/game/serious-sam-shatterverse/"
            "user-reviews/?platform=xbox-series-x",
        )
        self.assertIsNone(result)


def _mutate_nuxt_payload(html: str, mutate: Callable[[list[object]], None]) -> str:
    """Round-trips the real `__NUXT_DATA__` payload embedded in `html` through a mutator, for
    tests that need one specific corrupted field on top of an otherwise fully real, live-observed
    page -- rather than a hand-built minimal payload that would not prove anything about how the
    real, positionally-indexed page shape degrades."""
    marker = 'id="__NUXT_DATA__">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])
    mutate(payload)
    return html[:start] + json.dumps(payload) + html[end:]


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

    def test_malformed_criticscoresummary_raises_instead_of_reporting_a_natural_tbd(self) -> None:
        """HRD-01 / IMP-02's documented known limitation: every live-observed platform record
        carries `criticScoreSummary` as a dict, with only its `score` field ever null for a
        genuine tbd Metascore. A record where the container itself resolves to something else
        (a future markup/schema change) must be diagnosed, not silently reported as tbd."""

        def corrupt(payload: list[object]) -> None:
            for record in payload:
                if isinstance(record, dict) and "relatedGameId" in record and "slug" in record:
                    record["criticScoreSummary"] = record["name"]  # points at a string, not a dict
                    return
            raise AssertionError("fixture has no platform record to corrupt")

        html = _mutate_nuxt_payload(_read("elden_ring_detail.min.html"), corrupt)
        with self.assertRaises(MetacriticParseError):
            parse_game_detail(html, DETAIL_URL)

    def test_missing_lead_userscore_widget_container_raises_instead_of_reporting_a_natural_tbd(
        self,
    ) -> None:
        """HRD-01 / IMP-02's documented known limitation, userscore side: every live-observed
        page carries the `global-score-wrapper` container even for a genuine tbd Userscore (see
        `LiveContractStrayUserScoreWidgetTests`). Its total absence (a future markup change) must
        be diagnosed, not silently reported the same way as a real tbd score."""
        html = _read("elden_ring_detail.min.html").replace(
            'data-testid="global-score-wrapper"', 'data-testid="global-score-wrapper-renamed"'
        )
        with self.assertRaises(MetacriticParseError):
            parse_game_detail(html, DETAIL_URL)


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


class ParseOptionalMetadataTests(SimpleTestCase):
    def test_the_real_fixture_yields_release_date_publishers_and_content_rating(self) -> None:
        dto = parse_game_detail(_read("elden_ring_detail.min.html"), DETAIL_URL)

        self.assertEqual(dto.release_date, date(2022, 2, 25))
        self.assertEqual(dto.publishers, ("Bandai Namco Games", "From Software"))
        self.assertEqual(dto.content_rating, "M")

    def test_release_date_accepts_iso_dates_and_ignores_anything_else(self) -> None:
        self.assertEqual(_extract_release_date("2026-09-19"), date(2026, 9, 19))
        self.assertEqual(_extract_release_date("2026-09-19T00:00:00.000Z"), date(2026, 9, 19))
        for bad in (None, 5, "", "TBD", "2026-13-40", ["2026-09-19"]):
            self.assertIsNone(_extract_release_date(bad), bad)

    def test_publishers_accept_one_or_many_organisations_and_drop_noise(self) -> None:
        one = {"@type": "Organization", "name": "  Devolver   Digital "}
        self.assertEqual(_extract_publishers(one), ("Devolver Digital",))
        many = [one, {"name": "Devolver Digital"}, {"name": ""}, {"nope": 1}, "text", {"name": 7}]
        self.assertEqual(_extract_publishers(many), ("Devolver Digital",))
        for bad in (None, "Devolver", [], [{"name": "x" * 256}]):
            self.assertIsNone(_extract_publishers(bad), bad)

    def test_content_rating_is_a_short_string_or_absent(self) -> None:
        self.assertEqual(_extract_content_rating(" E10+ "), "E10+")
        for bad in (None, 3, "", "   ", "x" * 17):
            self.assertIsNone(_extract_content_rating(bad), bad)
