"""IMP-02/03 R19: malformed source data cannot poison a batch or overwrite good data."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from catalog.ingest import ingest_game
from catalog.models import Game, SourceFetch
from django.test import TestCase
from metacritic.dto import FetchEvidence, GameDTO
from metacritic.errors import MetacriticParseError
from metacritic.parser import _extract_user_score, _parse_platform
from processing.models import DailyCandidate, ProcessingLease, ProcessingRun
from processing.scheduler import run_tick

from tests.test_catalog_ingest import DETAIL_URL, _game, _platform
from tests.test_catalog_ingest import FakeGateway as DetailGateway
from tests.test_processing_selector import FakeGateway, _evidence, _game_dto, _identity
from tests.test_reviews_collector import FakeClock
from tests.test_reviews_snapshots import NOW


class SourceValidationTests(TestCase):
    def test_userscore_parser_distinguishes_invalid_numeric_labels_from_absence(self) -> None:
        for score in ("-1", "10.1", "8.55", "NaN", "Infinity", "bad"):
            with self.subTest(score=score), self.assertRaises(MetacriticParseError):
                _extract_user_score(
                    BeautifulSoup(
                        f'<span title="User score {score} out of 10"></span>', "html.parser"
                    )
                )
        self.assertIsNone(
            _extract_user_score(BeautifulSoup("<span>No scores</span>", "html.parser"))
        )

    def test_bad_secondary_userscore_preserves_previous_score_with_invalid_evidence(self) -> None:
        platform = replace(_platform(), is_lead_platform=False)
        dto = _game(platforms=(platform,))
        clock = FakeClock(NOW)
        assert platform.user_reviews_path is not None
        url = urljoin(DETAIL_URL, platform.user_reviews_path)
        good = DetailGateway(dto, platform_userscores={url: Decimal("7.6")})
        self.assertTrue(ingest_game(good, clock, DETAIL_URL).ok)
        bad = DetailGateway(dto, platform_userscores={url: Decimal("99")})
        self.assertTrue(ingest_game(bad, clock, DETAIL_URL).ok)
        self.assertEqual(Game.objects.get().platforms.get().userscore, Decimal("7.6"))
        self.assertTrue(
            SourceFetch.objects.filter(outcome="invalid", error_code="invalid_userscore").exists()
        )

    def test_parser_rejects_out_of_range_and_wrong_type_metascores(self) -> None:
        for score in (-1, 101, True, "90", 90.5):
            with self.subTest(score=score), self.assertRaises(MetacriticParseError):
                _parse_platform(
                    ["p1", "PC", "gp1", "pc", {"score": 5}, score],
                    {"id": 0, "name": 1, "relatedGameId": 2, "slug": 3, "criticScoreSummary": 4},
                )

    def test_invalid_dto_does_not_overwrite_existing_good_values(self) -> None:
        clock = FakeClock(NOW)
        good = _game()
        self.assertTrue(ingest_game(DetailGateway(good), clock, DETAIL_URL).ok)
        for changed in (
            replace(good, title="x" * 256),
            replace(good, platforms=(_platform(metascore=101),)),
            replace(good, platforms=(_platform(userscore=Decimal("NaN")),)),
            replace(good, platforms=(_platform(userscore=Decimal("10.1")),)),
            replace(good, platforms=(_platform(userscore=Decimal("8.55")),)),
        ):
            with self.subTest(changed=changed):
                result = ingest_game(DetailGateway(changed), clock, DETAIL_URL)
                self.assertFalse(result.ok)
                self.assertEqual(result.fetch_outcome, "invalid")
                saved = Game.objects.get()
                self.assertEqual(saved.title, good.title)
                self.assertEqual(saved.platforms.get().metascore, 94)

    def test_valid_zero_and_maximum_scores_are_preserved(self) -> None:
        for metascore, userscore in ((0, Decimal("0")), (100, Decimal("10")), (None, None)):
            with self.subTest(metascore=metascore):
                dto = _game(
                    source_game_id=str(metascore),
                    canonical_locator=f"/game/{metascore}/",
                    platforms=(
                        _platform(
                            source_game_platform_id=str(metascore),
                            metascore=metascore,
                            userscore=userscore,
                        ),
                    ),
                )
                self.assertTrue(ingest_game(DetailGateway(dto), FakeClock(NOW), DETAIL_URL).ok)

    def test_bad_game_is_classified_and_next_game_in_batch_still_commits(self) -> None:
        gateway = FakeGateway(new_releases=[_identity(1), _identity(2)])

        def fetch(url: str) -> tuple[GameDTO | None, FetchEvidence]:
            n = 1 if url.endswith("g1/") else 2
            dto = _game_dto(n)
            if n == 1:
                dto = replace(dto, platforms=(_platform(metascore=101),))
            return dto, _evidence("game_detail")

        with patch.object(gateway, "fetch_game", side_effect=fetch):
            result = run_tick(gateway, FakeClock(NOW))
        self.assertEqual(
            (
                result.run.status,
                result.run.selected_count,
                result.run.processed_count,
                result.run.failed_count,
            ),
            ("partial", 2, 1, 1),
        )
        self.assertIsNotNone(result.run.ended_at)
        self.assertEqual(DailyCandidate.objects.get(game__source_game_id="g1").state, "retryable")
        self.assertEqual(DailyCandidate.objects.get(game__source_game_id="g2").state, "processed")
        self.assertTrue(
            SourceFetch.objects.filter(outcome="invalid", error_code="invalid_game_data").exists()
        )

    def test_unexpected_exception_still_closes_run_and_releases_lease(self) -> None:
        gateway = FakeGateway(new_releases=[_identity(1), _identity(2)])
        with patch.object(gateway, "fetch_game", side_effect=RuntimeError("unexpected")):
            with self.assertRaises(RuntimeError):
                run_tick(gateway, FakeClock(NOW))
        current = ProcessingRun.objects.get()
        self.assertEqual(
            (current.status, current.error_code, current.selected_count, current.failed_count),
            ("failed", "unexpected_error", 2, 1),
        )
        self.assertIsNotNone(current.ended_at)
        self.assertIsNone(ProcessingLease.objects.get().owner_run_id)
        self.assertEqual(DailyCandidate.objects.get(game__source_game_id="g1").state, "retryable")
