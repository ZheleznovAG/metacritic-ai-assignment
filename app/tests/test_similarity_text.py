"""`similarity.text`: pure ranking, no database, no model (3.0.0 `rank`, 2.0.0 baseline)."""

from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase
from similarity import text

from tests.similarity_fakes import BagOfWordsEmbedder

TOPICS = {
    "dragons": "dragon sword castle knight kingdom quest magic tower siege armor",
    "racing": "racing track lap drift engine circuit speed tire garage overtake",
    "farming": "farm crops harvest seeds tractor barn village season orchard barley",
}


def _catalogue() -> tuple[list[int], list[str]]:
    ids: list[int] = []
    texts: list[str] = []
    for index, (topic, words) in enumerate(TOPICS.items()):
        vocabulary = words.split()
        for copy in range(4):
            ids.append(10 * (index + 1) + copy)
            rotated = vocabulary[copy:] + vocabulary[:copy]
            texts.append(f"{topic} game {copy}. Genre. " + " ".join(rotated))
    # Unrelated filler so the z-scores have a realistic background.
    for filler in range(30):
        ids.append(100 + filler)
        texts.append(f"filler {filler}. Other. unique{filler} word{filler} thing{filler * 7} extra")
    return ids, texts


def _rank() -> dict[int, tuple[text.Neighbor, ...]]:
    ids, texts = _catalogue()
    return text.rank_neighbors(ids, texts, BagOfWordsEmbedder().embed(texts))


class HelpersTests(SimpleTestCase):
    def test_a_description_needs_enough_text_to_take_part(self) -> None:
        self.assertFalse(text.has_signal(None))
        self.assertFalse(text.has_signal("  short  "))
        self.assertTrue(text.has_signal("x" * text.MIN_DESCRIPTION_CHARS))

    def test_game_text_joins_title_genres_and_description_and_is_capped(self) -> None:
        self.assertEqual(text.game_text("T", ("a", "b"), "Desc"), "T. a, b. Desc")
        self.assertEqual(len(text.game_text("T", (), "x" * 5000)), text.MAX_TEXT_CHARS)

    def test_tokenize_lowercases_and_drops_short_words_and_stopwords(self) -> None:
        self.assertEqual(
            text.tokenize("The Dragon's Sword, an epic GAME!"), ["dragon's", "sword", "epic"]
        )

    def test_tfidf_similarity_is_one_for_identical_texts_and_zero_without_shared_terms(
        self,
    ) -> None:
        matrix = text.tfidf_similarity(
            ["alpha beta gamma", "alpha beta gamma", "delta epsilon zeta", "alpha delta"]
        )
        self.assertAlmostEqual(float(matrix[0, 1]), 1.0, places=5)
        self.assertAlmostEqual(float(matrix[0, 2]), 0.0, places=5)
        self.assertGreater(float(matrix[0, 3]), 0.0)


class RankingTests(SimpleTestCase):
    def test_related_games_are_each_others_nearest_neighbours_and_unrelated_ones_are_not(
        self,
    ) -> None:
        ranked = _rank()

        for first in (10, 20, 30):
            cluster = {first, first + 1, first + 2, first + 3}
            neighbours = {n.game_id for n in ranked[first]}
            self.assertTrue(neighbours, first)
            self.assertLessEqual(neighbours, cluster - {first})

    def test_results_are_capped_ordered_deterministic_and_never_contain_the_query(self) -> None:
        ranked = _rank()
        again = _rank()

        self.assertEqual(ranked, again)
        for game_id, neighbours in ranked.items():
            self.assertLessEqual(len(neighbours), text.MAX_RESULTS)
            self.assertNotIn(game_id, [n.game_id for n in neighbours])
            scores = [n.score for n in neighbours]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertTrue(all(score >= text.MIN_FUSED_SCORE for score in scores))

    def test_a_game_without_a_real_peer_gets_no_results_instead_of_filler(self) -> None:
        ranked = _rank()

        self.assertEqual(ranked[100], ())

    def test_input_order_does_not_change_the_result(self) -> None:
        ids, texts = _catalogue()
        vectors = BagOfWordsEmbedder().embed(texts)
        order = list(reversed(range(len(ids))))

        shuffled = text.rank_neighbors(
            [ids[i] for i in order], [texts[i] for i in order], vectors[order]
        )

        self.assertEqual(shuffled, _rank())

    def test_equal_scores_are_broken_by_the_saved_game_id(self) -> None:
        ids = [7, 3, 5, 9]
        texts = ["same words here"] * 4
        vectors = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (4, 1))
        original = text.MIN_FUSED_SCORE
        text.MIN_FUSED_SCORE = -1e9
        try:
            ranked = text.rank_neighbors(ids, texts, vectors)
        finally:
            text.MIN_FUSED_SCORE = original

        self.assertEqual([n.game_id for n in ranked[9]], [3, 5, 7])

    def test_fewer_than_two_games_have_no_neighbours(self) -> None:
        self.assertEqual(text.rank_neighbors([], [], np.zeros((0, 2), dtype=np.float32)), {})
        single = text.rank_neighbors([1], ["only"], np.ones((1, 2), dtype=np.float32))
        self.assertEqual(single, {1: ()})

    def test_inconsistent_or_duplicate_inputs_are_rejected(self) -> None:
        vectors = np.ones((2, 2), dtype=np.float32)
        with self.assertRaises(ValueError):
            text.rank_neighbors([1, 2], ["a"], vectors)
        with self.assertRaises(ValueError):
            text.rank_neighbors([1, 1], ["a", "b"], vectors)


class DescriptionProblemTests(SimpleTestCase):
    def test_legacy_app_listings_are_not_trusted_to_describe_the_game(self) -> None:
        for description in (
            "Tilt your iPhone or iPad to dodge oncoming cars and potholes on the crazy highway.",
            "??Temporary freebie!??The most addictive game in the Appstore history, try it now!",
            "? High Castle Block ? is a simple and addictive puzzle game about stacking blocks.",
            "Do you have reflex skills? Play the most addictive reflex game in the app store!",
            "FREE for a limited time only! Collect coins and unlock characters in this runner.",
        ):
            with self.subTest(description=description):
                self.assertIsNotNone(text.description_problem("Kamikaze Dolphin", description))

    def test_a_description_that_introduces_another_game_is_not_trusted(self) -> None:
        problem = text.description_problem(
            "Ashfall Keep", "Skatpalast offers you Skat, the most popular card game in Germany."
        )
        self.assertEqual(problem, "describes another game (Skatpalast)")

    def test_ordinary_descriptions_are_trusted(self) -> None:
        for title, description in (
            (
                "Out of Range",
                "Out of Range is an intense arcade twin-stick shooter with arena waves.",
            ),
            ("HELLDROP", "HELL DROP is a roguelite action shooter with modular ship-building."),
            (
                "Groober",
                "You are a taxi service algorithm. Balance the corporates and the drivers.",
            ),
            (
                "Deep Dungeon II",
                "The classic Humming Bird Soft RPG is back! Defeat the Demon King.",
            ),
            ("Why?", "What would you do? Solve riddles in a quiet town, one question at a time."),
            (
                "My Fishing World 2",
                "永久免费写实多人钓鱼模拟沙盒，支持单人野钓、四人组队休闲野钓、自定义大型联机赛事。",
            ),
        ):
            with self.subTest(title=title):
                self.assertIsNone(text.description_problem(title, description))

    def test_missing_or_short_descriptions_are_reported(self) -> None:
        self.assertEqual(text.description_problem("T", None), "no description")
        self.assertEqual(text.description_problem("T", "  tiny "), "no description")


def _item(game_id: int, title: str, genre: str, description: str | None) -> text.Item:
    embedder = BagOfWordsEmbedder()
    label = text.label_text(title, (genre,))
    full = None
    if text.description_problem(title, description) is None:
        full = text.game_text(title, (genre,), description or "")
    return text.Item(
        game_id=game_id,
        genres=(genre,),
        label_text=label,
        label_vector=embedder.embed([label])[0],
        text=full,
        vector=None if full is None else embedder.embed([full])[0],
    )


def _catalogue_items() -> list[text.Item]:
    items = []
    for index, (topic, words) in enumerate(TOPICS.items()):
        vocabulary = words.split()
        for copy in range(4):
            rotated = vocabulary[copy:] + vocabulary[:copy]
            items.append(
                _item(10 * (index + 1) + copy, f"{topic} saga {copy}", topic, " ".join(rotated))
            )
    for filler in range(30):
        items.append(
            _item(
                100 + filler,
                f"filler {filler}",
                f"other{filler}",
                f"unique{filler} word{filler} thing{filler * 7} extra",
            )
        )
    return items


class CatalogueRankingTests(SimpleTestCase):
    def test_related_games_are_found_and_explained(self) -> None:
        ranked = text.rank(_catalogue_items())

        for first in (10, 20, 30):
            cluster = {first + 1, first + 2, first + 3}
            neighbours = ranked[first]
            self.assertTrue(neighbours)
            self.assertLessEqual({n.game_id for n in neighbours}, cluster)
            self.assertTrue(
                all(n.shared_genre and n.basis == text.BASIS_DESCRIPTION for n in neighbours)
            )
            for neighbour in neighbours:
                self.assertTrue(neighbour.shared_terms)
                self.assertLessEqual(len(neighbour.shared_terms), text.MAX_SHARED_TERMS)
                self.assertNotIn(list(TOPICS)[first // 10 - 1], neighbour.shared_terms)

    def test_a_junk_described_game_is_matched_by_title_and_genre_not_by_its_foreign_text(
        self,
    ) -> None:
        items = _catalogue_items()
        # Titled and labelled as racing, but described as a dragon game from an old app listing.
        items.append(_item(40, "racing saga turbo", "racing", "Download now! " + TOPICS["dragons"]))

        ranked = text.rank(items)

        self.assertTrue(ranked[40])
        self.assertLessEqual({n.game_id for n in ranked[40]}, {20, 21, 22, 23})
        self.assertTrue(all(n.basis == text.BASIS_TITLE for n in ranked[40]))
        for dragon in (10, 11, 12, 13):
            self.assertNotIn(40, {n.game_id for n in ranked[dragon]})

    def test_a_game_without_a_description_now_gets_title_and_genre_matches(self) -> None:
        items = _catalogue_items() + [_item(41, "farming saga harvest", "farming", None)]

        ranked = text.rank(items)

        self.assertLessEqual({n.game_id for n in ranked[41]}, {30, 31, 32, 33})
        self.assertTrue(ranked[41])

    def test_invariants_hold_and_input_order_does_not_matter(self) -> None:
        items = _catalogue_items() + [_item(42, "lonely", "nothing", None)]
        ranked = text.rank(items)

        self.assertEqual(text.rank(list(reversed(items))), ranked)
        for game_id, neighbours in ranked.items():
            ids = [n.game_id for n in neighbours]
            self.assertLessEqual(len(ids), text.MAX_RESULTS)
            self.assertNotIn(game_id, ids)
            self.assertEqual(len(ids), len(set(ids)))
            scores = [n.score for n in neighbours]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertTrue(all(score >= text.MIN_FUSED_SCORE for score in scores))
        self.assertEqual(ranked[100], ())  # no real peer: no filler

    def test_a_lone_described_game_falls_back_to_its_label(self) -> None:
        items = [
            _item(1, "dragon quest", "rpg", "A dragon quest across a large and dangerous kingdom."),
            _item(2, "dragon quest two", "rpg", None),
        ]
        with patch.object(text, "MIN_FUSED_SCORE", -1e9):
            ranked = text.rank(items)

        self.assertEqual([n.game_id for n in ranked[1]], [2])
        self.assertEqual(ranked[1][0].basis, text.BASIS_TITLE)

    def test_bad_inputs_are_rejected_and_tiny_catalogues_are_empty(self) -> None:
        one = _item(1, "a game", "rpg", None)
        self.assertEqual(text.rank([]), {})
        self.assertEqual(text.rank([one]), {1: ()})
        with self.assertRaises(ValueError):
            text.rank([one, one])
        with self.assertRaises(ValueError):
            text.rank([one, text.Item(2, ("rpg",), "x", one.label_vector, text="only text")])
