from datetime import UTC, datetime

from catalog.models import Game, GameAlias, GamePlatform
from django.db import IntegrityError, transaction
from django.test import TestCase

NOW = datetime(2026, 9, 11, tzinfo=UTC)


def _make_game(source_game_id: str = "1", locator: str = "/game/a/") -> Game:
    return Game.objects.create(
        source="metacritic", source_game_id=source_game_id, canonical_locator=locator, title="A"
    )


class GameConstraintTests(TestCase):
    def test_source_and_source_game_id_are_unique(self) -> None:
        _make_game(source_game_id="1", locator="/game/a/")
        with self.assertRaises(IntegrityError), transaction.atomic():
            _make_game(source_game_id="1", locator="/game/a-remastered/")


class GameAliasConstraintTests(TestCase):
    def test_source_and_locator_are_unique(self) -> None:
        game = _make_game()
        other = _make_game(source_game_id="2", locator="/game/b/")
        GameAlias.objects.create(
            game=game, source="metacritic", locator="/game/a/", first_seen_at=NOW, last_seen_at=NOW
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            GameAlias.objects.create(
                game=other,
                source="metacritic",
                locator="/game/a/",
                first_seen_at=NOW,
                last_seen_at=NOW,
            )


class GamePlatformConstraintTests(TestCase):
    def test_game_and_source_platform_id_are_unique(self) -> None:
        game = _make_game()
        GamePlatform.objects.create(
            game=game,
            source="metacritic",
            source_platform_id="p1",
            source_game_platform_id="r1",
            slug="pc",
            name="PC",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            GamePlatform.objects.create(
                game=game,
                source="metacritic",
                source_platform_id="p1",
                source_game_platform_id="r2",
                slug="pc-2",
                name="PC 2",
            )

    def test_source_and_source_game_platform_id_are_unique(self) -> None:
        game = _make_game()
        other = _make_game(source_game_id="2", locator="/game/b/")
        GamePlatform.objects.create(
            game=game,
            source="metacritic",
            source_platform_id="p1",
            source_game_platform_id="r1",
            slug="pc",
            name="PC",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            GamePlatform.objects.create(
                game=other,
                source="metacritic",
                source_platform_id="p2",
                source_game_platform_id="r1",
                slug="pc",
                name="PC",
            )

    def test_metascore_out_of_range_is_rejected(self) -> None:
        game = _make_game()
        with self.assertRaises(IntegrityError), transaction.atomic():
            GamePlatform.objects.create(
                game=game,
                source="metacritic",
                source_platform_id="p1",
                source_game_platform_id="r1",
                slug="pc",
                name="PC",
                metascore=101,
            )

    def test_userscore_out_of_range_is_rejected(self) -> None:
        game = _make_game()
        with self.assertRaises(IntegrityError), transaction.atomic():
            GamePlatform.objects.create(
                game=game,
                source="metacritic",
                source_platform_id="p1",
                source_game_platform_id="r1",
                slug="pc",
                name="PC",
                userscore="10.1",
            )

    def test_null_scores_are_allowed(self) -> None:
        game = _make_game()
        platform = GamePlatform.objects.create(
            game=game,
            source="metacritic",
            source_platform_id="p1",
            source_game_platform_id="r1",
            slug="pc",
            name="PC",
        )
        self.assertIsNone(platform.metascore)
        self.assertIsNone(platform.userscore)
