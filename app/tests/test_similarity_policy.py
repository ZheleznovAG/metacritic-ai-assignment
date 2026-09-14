"""IMP-06 / SIM-01 / R-SIM-01: policy invariants beyond the frozen quality cases."""

from dataclasses import replace
from itertools import permutations

from django.test import SimpleTestCase
from similarity.policy import POLICY_ID, POLICY_VERSION, SavedGame, rank


class SimilarityPolicyTests(SimpleTestCase):
    def setUp(self) -> None:
        self.query = SavedGame(1, "Anchor", ("Action RPG", "Role-Playing"), ("pc",), "Studio")

    def test_exact_relation_ranks_before_partial_with_explainable_score(self) -> None:
        partial = SavedGame(2, "A partial", ("Role-Playing", "Strategy"))
        close = SavedGame(3, "Z close", self.query.genres)
        first, second = rank(1, (self.query, partial, close))
        self.assertEqual((first.game_id, first.score), (3, 1.0))
        self.assertEqual(first.shared_genres, ("action rpg", "role-playing"))
        self.assertEqual((second.game_id, second.score), (2, 1 / 3))
        self.assertEqual((first.policy_id, first.policy_version), (POLICY_ID, POLICY_VERSION))

    def test_blank_and_duplicate_genres_do_not_manufacture_gain(self) -> None:
        candidate = SavedGame(2, "Peer", ("  ACTION   RPG ", "action rpg", "", " \t"))
        result = rank(1, (self.query, candidate))
        self.assertEqual(result[0].score, 0.5)
        self.assertEqual(result[0].shared_genres, ("action rpg",))
        self.assertEqual(rank(1, (replace(self.query, genres=(" ",)), candidate)), ())

    def test_developer_platform_and_equal_titles_cannot_admit_unrelated_games(self) -> None:
        distractor = replace(self.query, id=2, genres=("Racing",))
        self.assertEqual(rank(1, (self.query, distractor)), ())

    def test_unused_features_do_not_affect_scores_or_order(self) -> None:
        peer = replace(self.query, id=2)
        before = rank(1, (self.query, peer))
        self.assertEqual(before, rank(1, (self.query, replace(peer, developer=None, platforms=()))))

    def test_ties_use_casefolded_title_then_saved_id_for_every_input_order(self) -> None:
        catalog = (
            self.query,
            replace(self.query, id=4, title="Peer"),
            replace(self.query, id=3, title="peer"),
            replace(self.query, id=2, title="Apple"),
        )
        for ordered in permutations(catalog):
            self.assertEqual([r.game_id for r in rank(1, ordered)], [2, 3, 4])

    def test_cap_and_repeated_saved_rows_never_duplicate_results(self) -> None:
        peers = tuple(replace(self.query, id=i) for i in range(2, 10))
        results = rank(1, (self.query, *peers, *peers))
        self.assertEqual([r.game_id for r in results], [2, 3, 4, 5, 6])

    def test_empty_self_only_and_missing_query_produce_no_results(self) -> None:
        self.assertEqual(rank(1, ()), ())
        self.assertEqual(rank(1, (self.query,)), ())
        self.assertEqual(rank(99, (self.query, replace(self.query, id=2))), ())
        self.assertEqual(rank(True, (self.query, replace(self.query, id=2))), ())

    def test_conflicting_saved_identity_fails_in_either_input_order(self) -> None:
        peer = replace(self.query, id=2)
        conflicting = replace(peer, genres=("Puzzle",))
        for repeated in ((peer, conflicting), (conflicting, peer)):
            with self.assertRaises(ValueError):
                rank(1, (self.query, *repeated))

    def test_invalid_saved_ids_are_not_returned_as_results(self) -> None:
        for pk in (True, 0, -1):
            with self.subTest(pk=pk), self.assertRaises(ValueError):
                rank(1, (self.query, replace(self.query, id=pk)))
