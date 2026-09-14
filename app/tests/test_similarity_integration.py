"""SIM-VER-01 / AC-SIM-01–03: saved catalog -> unchanged policy -> card/navigation."""

import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from catalog.models import Game
from catalog.queries import list_similar_games
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from tests.test_catalog_queries_list import _platform


def saved(pk: int, title: str, genres: object) -> Game:
    return Game.objects.create(
        id=pk,
        source_game_id=f"similar-{pk}",
        canonical_locator=f"/game/similar-{pk}/",
        title=title,
        genres=genres,
    )


class SimilarityCatalogTests(TestCase):
    def test_every_frozen_result_survives_the_database_adapter_and_card(self) -> None:
        root = Path(__file__).resolve().parents[2] / "evals" / "similarity"
        cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))["cases"]
        report = json.loads((root / "comparison_report.json").read_text(encoding="utf-8"))
        expected = {
            case["case_id"]: case["selected_ids"]
            for case in report["methods"]["genre-jaccard"]["cases"]
        }
        for case in cases:
            for rows in (case["catalog"], list(reversed(case["catalog"]))):
                with self.subTest(case=case["id"], order=[row["id"] for row in rows]):
                    Game.objects.all().delete()
                    for row in rows:
                        saved(row["id"], row["title"], row["genres"])
                    first = list_similar_games(case["query_id"])
                    self.assertEqual([item.id for item in first], expected[case["id"]])
                    self.assertEqual(first, list_similar_games(case["query_id"]))
                    response = self.client.get(f"/games/{case['query_id']}/")
                    if not any(row["id"] == case["query_id"] for row in rows):
                        self.assertEqual(response.status_code, 404)
                        continue
                    self.assertEqual(response.status_code, 200)
                    soup = BeautifulSoup(response.content, "html.parser")
                    self.assertEqual(
                        [link.get("href") for link in soup.select(".similar-games a")],
                        [f"/games/{pk}/" for pk in expected[case["id"]]],
                    )

    def test_platform_multiplicity_does_not_duplicate_or_filter_similar_games(self) -> None:
        query = saved(1, "Query", ["Action RPG"])
        _platform(query, "pc", "PC")
        for pk in range(2, 9):
            game = saved(pk, "Same title", ["Action RPG"])
            for slug in ("pc", "ps5", "switch"):
                _platform(game, slug, slug)
        self.assertEqual([item.id for item in list_similar_games(1)], [2, 3, 4, 5, 6])

    def test_deleted_and_unknown_candidates_cannot_be_returned(self) -> None:
        saved(1, "Query", ["Puzzle"])
        peer = saved(2, "Peer", ["Puzzle"])
        self.assertEqual([item.id for item in list_similar_games(1)], [2])
        peer.delete()
        self.assertEqual(list_similar_games(1), [])
        self.assertEqual(list_similar_games(999), [])

    def test_read_only_snapshot_uses_no_http_or_enrichment(self) -> None:
        saved(1, "Query", ["  PUZZLE "])
        saved(2, "Peer", ["Puzzle", "puzzle"])
        with (
            patch("httpx.Client.send", side_effect=AssertionError("Unexpected HTTP")),
            CaptureQueriesContext(connection) as queries,
        ):
            result = list_similar_games(1)
        self.assertEqual(len(queries), 1)
        self.assertTrue(queries[0]["sql"].lstrip().startswith("SELECT"))
        self.assertEqual((result[0].id, result[0].score), (2, 1.0))
        self.assertEqual(result[0].shared_genres, ("puzzle",))
        self.assertEqual(
            (result[0].policy_id, result[0].policy_version), ("genre-jaccard", "1.0.0")
        )

    def test_malformed_stored_json_is_unknown_rather_than_fabricated_genres(self) -> None:
        saved(1, "Query", ["Puzzle"])
        peer = saved(2, "Peer", ["Puzzle"])
        for value in ("Puzzle", {"name": "Puzzle"}, ["Puzzle", None], []):
            with self.subTest(value=value):
                Game.objects.filter(pk=peer.pk).update(genres=value)
                self.assertEqual(list_similar_games(1), [])
                self.assertEqual(list_similar_games(peer.pk), [])


class SimilarityNavigationTests(TestCase):
    def test_same_title_links_open_each_saved_id_and_preserve_list_context(self) -> None:
        saved(1, "Query", ["Puzzle"])
        first = saved(2, "Twin", ["Puzzle"])
        second = saved(3, "Twin", ["Puzzle"])
        first.description = "First saved identity"
        first.save(update_fields=["description"])
        second.description = "Second saved identity"
        second.save(update_fields=["description"])
        query = urlencode({"q": "Q & Ω", "platform": "pc"})
        response = self.client.get(f"/games/1/?{query}")
        soup = BeautifulSoup(response.content, "html.parser")
        links = soup.select(".similar-games a")
        self.assertEqual([link.get_text() for link in links], ["Twin", "Twin"])
        self.assertEqual(
            [link.get("href") for link in links], [f"/games/2/?{query}", f"/games/3/?{query}"]
        )
        for link, peer in zip(links, (first, second), strict=True):
            destination = self.client.get(str(link["href"]))
            self.assertEqual(destination.context["game"].id, peer.id)
            assert peer.description is not None
            self.assertContains(destination, peer.description)
            back = BeautifulSoup(destination.content, "html.parser").select_one(".game-card__back")
            assert back is not None
            self.assertEqual(back["href"], f"/?{query}")

    def test_empty_and_self_only_catalogs_have_honest_empty_state(self) -> None:
        self.assertEqual(list_similar_games(1), [])
        self.assertEqual(self.client.get("/games/1/").status_code, 404)
        saved(1, "Only game", ["Puzzle"])
        response = self.client.get("/games/1/")
        self.assertContains(response, "No similar games in the catalog yet.")
        self.assertNotContains(response, '<ul class="similar-games">')

    def test_source_labels_and_titles_are_escaped_in_recommendations(self) -> None:
        genre = '<img src=x onerror="bad()">'
        saved(1, "Query", [genre])
        saved(2, "<script>bad()</script>", [genre])
        response = self.client.get("/games/1/")
        soup = BeautifulSoup(response.content, "html.parser")
        section = soup.select_one(".game-card__similar")
        assert section is not None
        self.assertIsNone(section.find("script"))
        self.assertIsNone(section.find("img"))
        self.assertIn("<script>bad()</script>", section.get_text())
        self.assertIn(genre, section.get_text())
