"""SIM-VER-01 / AC-SIM-01-03: saved neighbours -> card, navigation and escaping."""

from datetime import UTC, datetime
from unittest.mock import patch
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from catalog.models import Game, GameNeighbors
from catalog.queries import list_similar_games
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from similarity import text as policy

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def saved(pk: int, title: str, genres: object = None) -> Game:
    return Game.objects.create(
        id=pk,
        source_game_id=f"similar-{pk}",
        canonical_locator=f"/game/similar-{pk}/",
        title=title,
        genres=["Puzzle"] if genres is None else genres,
    )


def neighbours(pk: int, *pairs: tuple[int, float], version: str = policy.POLICY_VERSION) -> None:
    GameNeighbors.objects.update_or_create(
        game_id=pk,
        defaults={
            "policy_version": version,
            "neighbors": [{"id": other, "score": score} for other, score in pairs],
            "computed_at": NOW,
        },
    )


class SimilarGamesQueryTests(TestCase):
    def test_saved_neighbours_are_returned_in_saved_order_with_genres_and_policy(self) -> None:
        saved(1, "Query")
        saved(2, "Second", ["Action RPG"])
        saved(3, "Third", ["Puzzle"])
        neighbours(1, (3, 6.5), (2, 4.1))

        result = list_similar_games(1)

        self.assertEqual([item.id for item in result], [3, 2])
        self.assertEqual([item.score for item in result], [6.5, 4.1])
        self.assertEqual(result[1].genres, ("Action RPG",))
        self.assertEqual(
            (result[0].policy_id, result[0].policy_version), ("text-hybrid", policy.POLICY_VERSION)
        )

    def test_a_row_from_another_policy_version_is_ignored(self) -> None:
        saved(1, "Query")
        saved(2, "Peer")
        neighbours(1, (2, 5.0), version="1.0.0")

        self.assertEqual(list_similar_games(1), [])

    def test_deleted_self_and_unknown_neighbours_are_dropped(self) -> None:
        saved(1, "Query")
        peer = saved(2, "Peer")
        neighbours(1, (2, 5.0), (1, 9.0), (999, 4.0))
        self.assertEqual([item.id for item in list_similar_games(1)], [2])
        peer.delete()
        self.assertEqual(list_similar_games(1), [])
        self.assertEqual(list_similar_games(999), [])

    def test_malformed_stored_neighbours_are_unknown_rather_than_fabricated(self) -> None:
        saved(1, "Query")
        saved(2, "Peer")
        for value in (
            "2",
            {"id": 2},
            [None, {"id": "2", "score": 5}, {"score": 5}, {"id": 2, "score": None}],
            [{"id": 2, "score": "high"}],
            [],
        ):
            with self.subTest(value=value):
                GameNeighbors.objects.update_or_create(
                    game_id=1,
                    defaults={
                        "policy_version": policy.POLICY_VERSION,
                        "neighbors": value,
                        "computed_at": NOW,
                    },
                )
                self.assertEqual(list_similar_games(1), [])

    def test_a_request_is_two_selects_and_uses_no_http_model_or_ranking(self) -> None:
        saved(1, "Query")
        saved(2, "Peer")
        neighbours(1, (2, 5.0))
        with (
            patch("httpx.Client.send", side_effect=AssertionError("Unexpected HTTP")),
            patch("similarity.text.rank_neighbors", side_effect=AssertionError("ranked")),
            CaptureQueriesContext(connection) as queries,
        ):
            result = list_similar_games(1)
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(q["sql"].lstrip().startswith("SELECT") for q in queries))
        self.assertEqual([item.id for item in result], [2])

    def test_same_titles_stay_distinct_saved_identities(self) -> None:
        saved(1, "Query")
        saved(2, "Same title")
        saved(3, "Same title")
        neighbours(1, (2, 5.0), (3, 4.9))

        self.assertEqual([item.id for item in list_similar_games(1)], [2, 3])


class SimilarityNavigationTests(TestCase):
    def test_same_title_links_open_each_saved_id_and_preserve_list_context(self) -> None:
        saved(1, "Query")
        first = saved(2, "Twin")
        second = saved(3, "Twin")
        first.description = "First saved identity"
        first.save(update_fields=["description"])
        second.description = "Second saved identity"
        second.save(update_fields=["description"])
        neighbours(1, (2, 5.0), (3, 4.0))
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

    def test_empty_and_unindexed_games_have_an_honest_empty_state(self) -> None:
        self.assertEqual(list_similar_games(1), [])
        self.assertEqual(self.client.get("/games/1/").status_code, 404)
        saved(1, "Only game")
        response = self.client.get("/games/1/")
        self.assertContains(response, "No similar games in the catalog yet.")
        self.assertNotContains(response, '<ul class="similar-games">')

    def test_source_labels_and_titles_are_escaped_in_recommendations(self) -> None:
        genre = '<img src=x onerror="bad()">'
        saved(1, "Query", [genre])
        saved(2, "<script>bad()</script>", [genre])
        neighbours(1, (2, 5.0))
        response = self.client.get("/games/1/")
        soup = BeautifulSoup(response.content, "html.parser")
        section = soup.select_one(".game-card__similar")
        assert section is not None
        self.assertIsNone(section.find("script"))
        self.assertIsNone(section.find("img"))
        self.assertIn("<script>bad()</script>", section.get_text())
        self.assertIn(genre, section.get_text())
