"""Data migration `catalog.0008`: entity-encoded descriptions saved by earlier fetches."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class UnescapeDescriptionsMigrationTests(TransactionTestCase):
    def test_only_entity_bearing_descriptions_are_rewritten(self) -> None:
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("catalog", "0007_game_release_date_publishers_content_rating")])
            old_apps = (
                MigrationExecutor(connection)
                .loader.project_state(
                    [("catalog", "0007_game_release_date_publishers_content_rating")]
                )
                .apps
            )
            Game = old_apps.get_model("catalog", "Game")
            rows = {
                "entities": "Fun&nbsp;game &bull; it&rsquo;s &amp;amp; more",
                "plain": "Tom & Jerry, 5 < 6",
                "empty": "",
            }
            for key, description in rows.items():
                Game.objects.create(
                    source="metacritic",
                    source_game_id=key,
                    canonical_locator=f"/game/{key}/",
                    title=key,
                    description=description,
                )
            Game.objects.create(
                source="metacritic",
                source_game_id="none",
                canonical_locator="/game/none/",
                title="none",
                description=None,
            )
            MigrationExecutor(connection).migrate(latest)
        finally:
            MigrationExecutor(connection).migrate(latest)

        from catalog.models import Game as CurrentGame

        by_id = {g.source_game_id: g.description for g in CurrentGame.objects.all()}
        self.assertEqual(by_id["entities"], "Fun game • it’s &amp; more")
        self.assertEqual(by_id["plain"], "Tom & Jerry, 5 < 6")
        self.assertEqual(by_id["empty"], "")
        self.assertIsNone(by_id["none"])
