import threading
from datetime import UTC, datetime
from unittest.mock import patch

from catalog.models import Game, GamePlatform
from django.db import connections
from django.test import TransactionTestCase
from metacritic.dto import FetchEvidence, ReviewPageDTO
from reviews import collector
from reviews import corpus as corpus_module
from reviews.models import ReviewCollectionJob, ReviewCorpus
from summaries.models import SummaryJob

from tests.test_reviews_collector import FakeClock, FakeGateway, _make_job
from tests.test_reviews_snapshots import page


def _make_completed_route(audience: str = "critic") -> tuple[Game, GamePlatform]:
    initial = _make_job(audience)
    clock = FakeClock(datetime(2026, 9, 12, tzinfo=UTC))
    claim = collector.claim_next_job(clock)
    assert claim is not None
    # Persist genuine page evidence/observations, leave only the builder race to this test.
    with patch("reviews.collector._maybe_build_corpus_and_summary_job"):
        collector.collect_one_page(FakeGateway({None: page(1, 2, 3)}), clock, claim)
    return initial.game_platform.game, initial.game_platform


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

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [], f"build() raised under real concurrency: {errors}")
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        assert results[0] is not None and results[1] is not None
        self.assertEqual(results[0].id, results[1].id)
        self.assertEqual(ReviewCorpus.objects.filter(game_id=game_id, audience="critic").count(), 1)

    def test_two_platforms_commit_terminal_pages_without_deadlock_or_lost_handoff(self) -> None:
        initial = _make_job()
        second_platform = GamePlatform.objects.create(
            game=initial.game_platform.game,
            source_platform_id="p2",
            source_game_platform_id="gp2",
            slug="ps5",
            name="PlayStation 5",
            critic_reviews_path="/game/g1/critic-reviews/?platform=ps5",
        )
        ReviewCollectionJob.objects.create(
            daily_candidate=initial.daily_candidate,
            game_platform=second_platform,
            audience="critic",
        )
        clock = FakeClock(datetime(2026, 9, 12, tzinfo=UTC))
        claims = [collector.claim_next_job(clock), collector.claim_next_job(clock)]
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def worker(index: int) -> None:
            try:
                claim = claims[index]
                assert claim is not None
                gateway = FakeGateway({None: page(1, 2, 3, suffix=str(index))})
                original_fetch = gateway.fetch_review_page

                def synchronized_fetch(
                    audience: str, game_slug: str, platform_slug: str, cursor: str | None
                ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
                    barrier.wait(timeout=5)
                    return original_fetch(audience, game_slug, platform_slug, cursor)

                with patch.object(gateway, "fetch_review_page", side_effect=synchronized_fetch):
                    collector.collect_one_page(gateway, clock, claim)
            except BaseException as error:  # noqa: BLE001 - report thread failures below
                errors.append(error)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(ReviewCollectionJob.objects.filter(state="complete").count(), 2)
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (1, 1))
        current = ReviewCorpus.objects.get()
        self.assertEqual((current.unique_count, current.selected_count), (6, 6))
        self.assertEqual(
            set(current.items.values_list("review__game_platform__slug", flat=True)), {"pc", "ps5"}
        )
