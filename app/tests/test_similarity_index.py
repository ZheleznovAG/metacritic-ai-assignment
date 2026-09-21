"""`catalog.similarity_index`: embedding upkeep and neighbour rebuild on PostgreSQL."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import SkipTest, mock

import numpy as np
from catalog import similarity_index
from catalog.models import Game, GameEmbedding, GameNeighbors
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from similarity import text as policy
from similarity.embedder import FastEmbedder

from tests.similarity_fakes import BagOfWordsEmbedder, ExplodingEmbedder

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
TOPICS = {
    "dragons": "dragon sword castle knight kingdom quest magic tower siege armor",
    "racing": "racing track lap drift engine circuit speed tire garage overtake",
}


class Clock:
    def __init__(self) -> None:
        self.instant = NOW

    def now_utc(self) -> datetime:
        return self.instant


def _game(pk: int, title: str, description: str | None, genres: object = None) -> Game:
    return Game.objects.create(
        id=pk,
        source_game_id=f"idx-{pk}",
        canonical_locator=f"/game/idx-{pk}/",
        title=title,
        description=description,
        genres=["Action"] if genres is None else genres,
    )


def _seed() -> None:
    for index, words in enumerate(TOPICS.values()):
        vocabulary = words.split()
        for copy in range(4):
            rotated = vocabulary[copy:] + vocabulary[:copy]
            _game(10 * (index + 1) + copy, f"Topic{index} {copy}", " ".join(rotated) + " epic")
    for filler in range(30):
        _game(
            100 + filler,
            f"Filler {filler}",
            f"unique{filler} word{filler} thing{filler * 7} plus some more filler text here",
        )


class EmbedPendingTests(TestCase):
    def test_games_without_enough_description_take_no_part(self) -> None:
        _game(1, "Empty", None)
        _game(2, "Short", "tiny")
        _game(3, "Real", "a long enough description of a real game about knights " * 2)

        embedder = BagOfWordsEmbedder()
        result = similarity_index.refresh(embedder, Clock())

        self.assertEqual(result.embedded, 1)
        self.assertEqual(list(GameEmbedding.objects.values_list("game_id", flat=True)), [3])

    def test_work_is_bounded_per_call_and_resumes_until_nothing_is_pending(self) -> None:
        _seed()
        total = Game.objects.count()
        embedder = BagOfWordsEmbedder()
        clock = Clock()

        first = similarity_index.refresh(embedder, clock, limit=16)

        self.assertEqual((first.embedded, first.rebuilt), (16, 0))
        self.assertEqual(first.pending, total - 16)
        self.assertEqual(GameNeighbors.objects.count(), 0)
        rounds = 1
        while True:
            step = similarity_index.refresh(embedder, clock, limit=16)
            rounds += 1
            if step.pending == 0:
                break
            self.assertLess(rounds, 10)
        self.assertGreater(step.rebuilt, 0)
        self.assertEqual(GameEmbedding.objects.count(), total)
        self.assertEqual(GameNeighbors.objects.count(), total)

    def test_unchanged_text_is_not_embedded_again_but_changed_text_is(self) -> None:
        _seed()
        embedder = BagOfWordsEmbedder()
        clock = Clock()
        while similarity_index.refresh(embedder, clock).pending:
            pass
        calls = len(embedder.calls)

        idle = similarity_index.refresh(embedder, clock)
        self.assertEqual((idle.embedded, idle.rebuilt), (0, 0))
        self.assertEqual(len(embedder.calls), calls)

        Game.objects.filter(pk=10).update(description="a completely different racing story " * 3)
        clock.instant += timedelta(minutes=5)
        changed = similarity_index.refresh(embedder, clock)
        self.assertEqual((changed.embedded, changed.pending), (1, 0))
        self.assertGreater(changed.rebuilt, 0)
        self.assertEqual(embedder.calls[-1][0][:8], "Topic0 0")

    def test_a_different_model_id_marks_every_embedding_as_pending(self) -> None:
        _seed()
        embedder = BagOfWordsEmbedder()
        while similarity_index.refresh(embedder, Clock()).pending:
            pass
        GameEmbedding.objects.update(model_id="some/other-model")

        result = similarity_index.refresh(embedder, Clock(), limit=100)

        self.assertEqual(result.embedded, Game.objects.count())
        self.assertEqual(GameEmbedding.objects.exclude(model_id=policy.MODEL_ID).count(), 0)


class NeighbourRebuildTests(TestCase):
    def _build(self) -> Clock:
        _seed()
        embedder = BagOfWordsEmbedder()
        clock = Clock()
        while similarity_index.refresh(embedder, clock, limit=100).pending:
            pass
        return clock

    def test_neighbours_are_saved_with_scores_and_the_policy_version(self) -> None:
        self._build()

        row = GameNeighbors.objects.get(game_id=10)

        self.assertEqual(row.policy_version, policy.POLICY_VERSION)
        self.assertEqual(row.computed_at, NOW)
        ids = [item["id"] for item in row.neighbors]
        self.assertTrue(ids)
        self.assertLessEqual(set(ids), {11, 12, 13})
        self.assertTrue(all(item["score"] >= policy.MIN_FUSED_SCORE for item in row.neighbors))

    def test_vectors_round_trip_as_little_endian_float32(self) -> None:
        self._build()

        vector = np.frombuffer(bytes(GameEmbedding.objects.get(game_id=10).vector), dtype="<f4")

        self.assertEqual(vector.shape, (64,))
        self.assertAlmostEqual(float(np.linalg.norm(vector)), 1.0, places=5)

    def test_a_current_index_is_not_rebuilt_but_a_policy_change_or_new_game_is(self) -> None:
        clock = self._build()
        embedder = BagOfWordsEmbedder()
        self.assertEqual(similarity_index.refresh(embedder, clock).rebuilt, 0)

        GameNeighbors.objects.update(policy_version="0.0.1")
        self.assertGreater(similarity_index.refresh(embedder, clock).rebuilt, 0)

        _game(500, "Newcomer", "dragon sword castle knight quest magic tower " * 2)
        rebuilt = similarity_index.refresh(embedder, clock)
        self.assertEqual((rebuilt.embedded, rebuilt.pending), (1, 0))
        self.assertEqual(GameNeighbors.objects.count(), Game.objects.count())

    def test_no_http_is_used_and_the_web_side_needs_no_ranking(self) -> None:
        with mock.patch("httpx.Client.send", side_effect=AssertionError("Unexpected HTTP")):
            self._build()


class DroppedGameTests(TestCase):
    def _build(self) -> tuple[Clock, BagOfWordsEmbedder]:
        _seed()
        embedder = BagOfWordsEmbedder()
        clock = Clock()
        while similarity_index.refresh(embedder, clock, limit=100).pending:
            pass
        return clock, embedder

    def test_a_game_that_loses_its_text_is_emptied_once_and_never_rebuilds_forever(self) -> None:
        clock, embedder = self._build()
        self.assertTrue(GameNeighbors.objects.get(game_id=11).neighbors)

        Game.objects.filter(pk=11).update(description="gone")
        clock.instant += timedelta(minutes=5)
        rebuilt = similarity_index.refresh(embedder, clock)

        self.assertGreater(rebuilt.rebuilt, 0)
        self.assertEqual(GameNeighbors.objects.get(game_id=11).neighbors, [])
        others = GameNeighbors.objects.exclude(game_id=11)
        self.assertFalse(any(11 == n["id"] for row in others for n in row.neighbors))
        settled = similarity_index.refresh(embedder, clock)
        self.assertEqual((settled.embedded, settled.rebuilt), (0, 0))

    def test_an_empty_catalogue_with_leftover_rows_does_not_crash_and_clears_them(self) -> None:
        clock, embedder = self._build()
        Game.objects.update(description="")

        result = similarity_index.refresh(embedder, clock)

        self.assertEqual(result.rebuilt, 0)
        self.assertFalse(GameNeighbors.objects.exclude(neighbors=[]).exists())
        self.assertEqual(similarity_index.refresh(embedder, clock).rebuilt, 0)

    def test_rows_are_upserted_in_batches_not_one_query_pair_per_game(self) -> None:
        clock, embedder = self._build()
        GameNeighbors.objects.update(policy_version="0.0.1")
        with CaptureQueriesContext(connection) as queries:
            similarity_index.refresh(embedder, clock)
        inserts = [q for q in queries if q["sql"].lstrip().upper().startswith("INSERT")]
        self.assertLessEqual(len(inserts), 2)


class MaintainerTests(TestCase):
    def test_an_unchanged_catalogue_is_not_reread_until_the_hourly_full_check(self) -> None:
        _seed()
        now = [0.0]
        maintainer = similarity_index.Maintainer(
            BagOfWordsEmbedder, interval=60, monotonic=lambda: now[0]
        )
        clock = Clock()
        while True:  # build the index
            step = maintainer.run_if_due(clock)
            now[0] += 1
            if step is not None and not step.pending:
                break
        now[0] += 100
        settled = maintainer.run_if_due(clock)  # one idle pass, after which it is settled
        assert settled is not None
        self.assertEqual((settled.embedded, settled.rebuilt), (0, 0))

        now[0] += 100
        with CaptureQueriesContext(connection) as queries:
            self.assertIsNone(maintainer.run_if_due(clock))
        self.assertLessEqual(len(queries), 2)  # only the two change-detecting aggregates

        Game.objects.filter(pk=10).update(updated_at=NOW + timedelta(days=1))
        now[0] += 100
        self.assertIsNotNone(maintainer.run_if_due(clock))  # a saved game wakes it at once
        now[0] += 4000
        self.assertIsNotNone(maintainer.run_if_due(clock))  # and it re-checks hourly regardless

    def test_it_runs_at_most_once_per_interval_and_continues_while_work_is_pending(self) -> None:
        _seed()
        instants = iter([0.0, 1.0, 2.0, 3.0, 100.0, 1000.0])
        maintainer = similarity_index.Maintainer(
            BagOfWordsEmbedder, interval=60, monotonic=lambda: next(instants)
        )
        clock = Clock()

        first = maintainer.run_if_due(clock)
        assert first is not None
        self.assertGreater(first.pending, 0)
        second = maintainer.run_if_due(clock)  # still pending: due again immediately
        assert second is not None
        results = [first, second]
        while results[-1].pending:
            follow = maintainer.run_if_due(clock)
            assert follow is not None
            results.append(follow)
        self.assertIsNone(maintainer.run_if_due(clock))  # inside the 60 s quiet interval

    def test_a_model_failure_is_contained_and_retried_later(self) -> None:
        _seed()
        instants = iter([0.0, 5.0, 700.0])
        maintainer = similarity_index.Maintainer(
            ExplodingEmbedder, interval=60, monotonic=lambda: next(instants)
        )

        with self.assertLogs("catalog.similarity_index", level="ERROR"):
            self.assertIsNone(maintainer.run_if_due(Clock()))
        self.assertIsNone(maintainer.run_if_due(Clock()))  # backing off, no second attempt

        with self.assertLogs("catalog.similarity_index", level="ERROR"):
            self.assertIsNone(maintainer.run_if_due(Clock()))  # retried after the back-off


class RealModelTests(TestCase):
    """Loads the real ONNX model; runs where the image (or a dev cache) provides it."""

    def test_the_real_model_embeds_similar_text_closer_than_unrelated_text(self) -> None:
        cache = os.environ.get("FASTEMBED_CACHE_PATH", "")
        if not cache or not Path(cache).is_dir():
            raise SkipTest("FASTEMBED_CACHE_PATH does not point at a baked model cache")
        embedder = FastEmbedder()

        rows = embedder.embed(
            [
                "A fantasy action RPG with dragons, swords and castles.",
                "Sword and sorcery role-playing adventure in a dragon-haunted kingdom.",
                "A realistic football manager simulation with transfers and tactics.",
            ]
        )

        self.assertEqual(rows.shape, (3, 384))
        self.assertEqual(rows.dtype, np.float32)
        np.testing.assert_allclose(np.linalg.norm(rows, axis=1), 1.0, atol=1e-5)
        self.assertGreater(float(rows[0] @ rows[1]), float(rows[0] @ rows[2]) + 0.2)
