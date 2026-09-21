"""`similarity.text` (policy `text-hybrid` 2.0.0): pure ranking, no database, no model."""

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
