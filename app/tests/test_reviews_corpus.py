import threading
from datetime import UTC, datetime

from catalog.models import Game, GamePlatform
from django.db import connections
from django.test import TransactionTestCase
from processing.models import DailyCandidate, DailyCycle
from reviews import corpus as corpus_module
from reviews.models import Review, ReviewCollectionJob, ReviewCorpus


def _make_completed_route(audience: str = "critic") -> tuple[Game, GamePlatform]:
    game = Game.objects.create(source_game_id="g1", canonical_locator="/game/g1/", title="Game 1")
    platform = GamePlatform.objects.create(
        game=game,
        source_platform_id="p1",
        source_game_platform_id="gp1",
        slug="pc",
        name="PC",
        critic_reviews_path="/game/g1/critic-reviews/?platform=pc",
        user_reviews_path="/game/g1/user-reviews/?platform=pc",
    )
    cycle = DailyCycle.objects.create(business_date="2026-09-12")
    candidate = DailyCandidate.objects.create(
        cycle=cycle, game=game, source_order=1, state="processed"
    )
    ReviewCollectionJob.objects.create(
        daily_candidate=candidate,
        game_platform=platform,
        audience=audience,
        state="complete",
        completed_at=datetime(2026, 9, 12, tzinfo=UTC),
        reported_total=3,
        fetched_count=3,
        unique_count=3,
    )
    for i in range(3):
        Review.objects.create(
            game_platform=platform,
            audience=audience,
            identity_key=f"id:{i}",
            text_original=f"Review text number {i} with real content.",
            content_sha256=f"sha{i}",
            first_seen_at=datetime(2026, 9, 12, tzinfo=UTC),
        )
    return game, platform


class ConcurrentBuildRaceTests(TransactionTestCase):
    def test_two_workers_completing_the_same_route_at_once_never_crash_and_agree_on_one_corpus(
        self,
    ) -> None:
        game, _platform = _make_completed_route()
        game_id = game.id
        barrier = threading.Barrier(2)
        results: list[ReviewCorpus | None] = [None, None]
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                barrier.wait(timeout=5)
                fresh_game = Game.objects.get(pk=game_id)
                results[index] = corpus_module.build(fresh_game, "critic")
            except BaseException as error:  # noqa: BLE001 - captured for the assertion below
                errors.append(error)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [], f"build() raised under real concurrency: {errors}")
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        assert results[0] is not None and results[1] is not None
        self.assertEqual(results[0].id, results[1].id)
        self.assertEqual(ReviewCorpus.objects.filter(game_id=game_id, audience="critic").count(), 1)
