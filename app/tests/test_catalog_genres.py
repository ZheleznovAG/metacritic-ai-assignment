"""IMP-06 / DATA-02 / R-DAT-01: observed genre -> DTO -> canonical storage/provenance."""

import json
from dataclasses import replace
from decimal import Decimal
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from catalog.ingest import ingest_game, resolve_game_identity
from catalog.models import Game, SourceFetch
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from metacritic.dto import GameDTO, GameIdentityDTO
from metacritic.errors import MetacriticParseError
from metacritic.parser import parse_game_detail

from tests.test_catalog_ingest import DETAIL_URL, FakeClock, FakeGateway, _game
from tests.test_metacritic_parser import FIXTURES


def detail_with_genre(value: object) -> GameDTO:
    soup = BeautifulSoup(
        (FIXTURES / "elden_ring_detail.min.html").read_text(encoding="utf-8"), "html.parser"
    )
    script = soup.find("script", attrs={"type": "application/ld+json"})
    assert script is not None and script.string is not None
    data = json.loads(script.string)
    data["genre"] = value
    script.string = json.dumps(data)
    return parse_game_detail(str(soup), DETAIL_URL)


class GenreParserTests(SimpleTestCase):
    def test_genre_is_read_from_the_existing_independent_source_fixture(self) -> None:
        html = (FIXTURES / "elden_ring_detail.min.html").read_text(encoding="utf-8")
        self.assertEqual(parse_game_detail(html, DETAIL_URL).genres, ("Action RPG",))

    def test_array_and_whitespace_preserve_complete_labels(self) -> None:
        self.assertEqual(
            detail_with_genre(["  Action   RPG ", "Role-Playing"]).genres,
            ("Action RPG", "Role-Playing"),
        )

    def test_natural_absence_and_empty_values_supply_no_new_genres(self) -> None:
        for value in (None, "", " \t", [], ["", " "]):
            with self.subTest(value=value):
                self.assertIsNone(detail_with_genre(value).genres)

    def test_malformed_values_are_not_coerced_into_recommendation_features(self) -> None:
        for value in (3, True, {"name": "Puzzle"}, [None], ["Puzzle", 3], "x\x00y", "x" * 256):
            with self.subTest(value=value), self.assertRaises(MetacriticParseError):
                detail_with_genre(value)


class GenreStorageTests(TestCase):
    def test_observed_parser_dto_is_persisted_with_its_own_fetch(self) -> None:
        dto = detail_with_genre("Action RPG")
        scores: dict[str, Decimal | None] = {
            urljoin(DETAIL_URL, platform.user_reviews_path): None
            for platform in dto.platforms
            if platform.user_reviews_path
        }
        result = ingest_game(FakeGateway(dto, platform_userscores=scores), FakeClock(), DETAIL_URL)
        self.assertTrue(result.ok)
        game = Game.objects.get()
        self.assertEqual(game.genres, ["action rpg"])
        self.assertEqual(game.genres_last_changed_fetch_id, game.last_changed_fetch_id)

    def test_normalization_deduplicates_in_source_order_and_replaces_known_values(self) -> None:
        for genres, expected in (
            ((" PUZZLE ", "puzzle", "Action  RPG"), ["puzzle", "action rpg"]),
            (("Racing",), ["racing"]),
        ):
            result = ingest_game(
                FakeGateway(replace(_game(), genres=genres)), FakeClock(), DETAIL_URL
            )
            self.assertTrue(result.ok)
            game = Game.objects.get()
            self.assertEqual(game.genres, expected)
            self.assertEqual(game.genres_last_changed_fetch_id, game.last_changed_fetch_id)
        self.assertEqual(Game.objects.count(), 1)

    def test_missing_genres_and_identity_refresh_keep_values_and_original_provenance(self) -> None:
        ingest_game(FakeGateway(replace(_game(), genres=("Puzzle",))), FakeClock(), DETAIL_URL)
        original = Game.objects.get()
        for genres in (None, ()):
            ingest_game(FakeGateway(replace(_game(), genres=genres)), FakeClock(), DETAIL_URL)
            game = Game.objects.get()
            self.assertEqual(game.genres, ["puzzle"])
            self.assertEqual(
                game.genres_last_changed_fetch_id, original.genres_last_changed_fetch_id
            )
            self.assertNotEqual(game.last_changed_fetch_id, game.genres_last_changed_fetch_id)
        resolve_game_identity(
            GameIdentityDTO(original.source_game_id, original.canonical_locator, "New title"),
            FakeClock().now_utc(),
        )
        original.refresh_from_db()
        self.assertEqual(original.genres, ["puzzle"])
        self.assertIsNotNone(original.genres_last_changed_fetch_id)

    def test_invalid_dto_does_not_overwrite_saved_features(self) -> None:
        good = replace(_game(), genres=("Puzzle",))
        ingest_game(FakeGateway(good), FakeClock(), DETAIL_URL)
        original = Game.objects.get()
        for value in ("Puzzle", ["Puzzle"], (None,), (" ",), ("x\x00y",), ("x" * 256,)):
            with self.subTest(value=value):
                bad = replace(good, genres=value)  # type: ignore[arg-type]
                result = ingest_game(FakeGateway(bad), FakeClock(), DETAIL_URL)
                self.assertFalse(result.ok)
                saved = Game.objects.get()
                self.assertEqual(saved.genres, ["puzzle"])
                self.assertEqual(
                    saved.genres_last_changed_fetch_id, original.genres_last_changed_fetch_id
                )
        self.assertTrue(SourceFetch.objects.filter(outcome="invalid").exists())


class GenreMigrationTests(TransactionTestCase):
    def test_existing_game_ids_and_core_data_survive_without_invented_genres(self) -> None:
        ingest_game(FakeGateway(_game()), FakeClock(), DETAIL_URL)
        original = Game.objects.get()
        executor = MigrationExecutor(connection)
        original_id = original.pk
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("catalog", "0005_alter_sourcefetch_outcome")])
            MigrationExecutor(connection).migrate(latest)
        finally:
            MigrationExecutor(connection).migrate(latest)
        original.refresh_from_db()
        self.assertEqual(
            (original.pk, original.title, original.developer),
            (original_id, "Elden Ring", "From Software"),
        )
        self.assertEqual(original.genres, [])
        self.assertIsNone(original.genres_last_changed_fetch_id)
        self.assertEqual(original.platforms.count(), 1)
