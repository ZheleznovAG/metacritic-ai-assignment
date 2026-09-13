"""IMP-03 / audit R02, R15: discovery must be lossless and resumable when bounded."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from catalog.models import Game
from django.test import TestCase
from metacritic.dto import BrowsePage, FetchEvidence
from processing.models import DailyCandidate, DailyCycle
from processing.scheduler import run_tick

from tests.test_processing_selector import FakeClock, FakeGateway, _evidence, _identity

START = datetime(2026, 9, 13, 9, tzinfo=UTC)


class DiscoveryRegressionTests(TestCase):
    def test_all_page_tails_are_processed_before_exhaustion(self) -> None:
        gateway = FakeGateway(
            new_releases=[_identity(1)],
            browse_pages={
                1: BrowsePage(tuple(_identity(i) for i in range(2, 26)), True),
                2: BrowsePage(tuple(_identity(i) for i in range(26, 50)), False),
            },
        )
        counts = []
        checkpoints = []
        with patch.object(gateway, "iter_browse", wraps=gateway.iter_browse) as browse:
            for hour in range(5):
                result = run_tick(gateway, FakeClock(START + timedelta(hours=hour)))
                counts.append(result.run.processed_count)
                cycle = DailyCycle.objects.get()
                checkpoints.append((cycle.phase, cycle.browse_next_page))
                self.assertEqual(result.outcome, "succeeded")

        self.assertEqual(counts, [1, 20, 20, 8, 0])
        self.assertEqual(
            checkpoints,
            [("browse", 1), ("browse", 1), ("browse", 2), ("exhausted", 3), ("exhausted", 3)],
        )
        self.assertEqual([call.args[0] for call in browse.call_args_list], [1, 1, 2, 2])
        self.assertEqual(
            list(
                DailyCandidate.objects.order_by("source_order").values_list(
                    "game__source_game_id", flat=True
                )
            ),
            [f"g{i}" for i in range(1, 50)],
        )
        self.assertEqual(Game.objects.count(), 49)

    def test_repeated_pages_stop_without_false_exhaustion_and_can_resume(self) -> None:
        gateway = FakeGateway(new_releases=[_identity(1)])
        run_tick(gateway, FakeClock(START))

        def repeated(page_number: int) -> tuple[BrowsePage, FetchEvidence]:
            if page_number > 5:
                self.fail("Discovery kept requesting a page with no progress")
            return BrowsePage((_identity(1),), True), _evidence("browse_page")

        with patch.object(gateway, "iter_browse", side_effect=repeated) as browse:
            result = run_tick(gateway, FakeClock(START + timedelta(hours=1)))

        self.assertEqual(browse.call_count, 2)
        self.assertEqual(result.outcome, "failed")
        self.assertEqual(result.run.error_code, "browse_repeated_page")
        cycle = DailyCycle.objects.get()
        self.assertEqual((cycle.phase, cycle.browse_next_page), ("browse", 2))
        gateway.browse_pages[2] = BrowsePage((_identity(2),), False)
        resumed = run_tick(gateway, FakeClock(START + timedelta(hours=2)))
        self.assertEqual(resumed.run.processed_count, 1)
        cycle.refresh_from_db()
        self.assertEqual(cycle.phase, "exhausted")

    def test_duplicates_and_overlap_preserve_first_source_order(self) -> None:
        gateway = FakeGateway(
            new_releases=[_identity(1), _identity(1)],
            browse_pages={
                1: BrowsePage((_identity(1), _identity(2), _identity(2)), True),
                2: BrowsePage((_identity(2), _identity(3), _identity(1)), False),
            },
        )
        first = run_tick(gateway, FakeClock(START))
        second = run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        self.assertEqual((first.run.processed_count, second.run.processed_count), (1, 2))
        self.assertEqual(second.outcome, "succeeded")
        self.assertEqual(
            list(
                DailyCandidate.objects.order_by("source_order").values_list(
                    "game__source_game_id", flat=True
                )
            ),
            ["g1", "g2", "g3"],
        )

    def test_retry_occupies_capacity_without_discarding_terminal_page_tail(self) -> None:
        gateway = FakeGateway(
            new_releases=[_identity(1)],
            failing_games={"g1"},
            browse_pages={1: BrowsePage(tuple(_identity(i) for i in range(2, 26)), False)},
        )
        run_tick(gateway, FakeClock(START))
        gateway.failing_games.clear()
        second = run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        self.assertEqual(second.run.processed_count, 20)
        self.assertEqual(DailyCycle.objects.get().phase, "browse")
        third = run_tick(gateway, FakeClock(START + timedelta(hours=2)))
        self.assertEqual(third.run.processed_count, 5)
        self.assertEqual(DailyCandidate.objects.filter(state="processed").count(), 25)
        self.assertEqual(DailyCycle.objects.get().phase, "exhausted")

    def test_failure_rereading_partial_page_retains_cursor_and_tail(self) -> None:
        gateway = FakeGateway(
            new_releases=[_identity(1)],
            browse_pages={1: BrowsePage(tuple(_identity(i) for i in range(2, 26)), False)},
        )
        run_tick(gateway, FakeClock(START))
        run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        gateway.failing_pages.add(1)
        failed = run_tick(gateway, FakeClock(START + timedelta(hours=2)))
        self.assertEqual(failed.outcome, "failed")
        cycle = DailyCycle.objects.get()
        self.assertEqual((cycle.phase, cycle.browse_next_page), ("browse", 1))
        gateway.failing_pages.clear()
        resumed = run_tick(gateway, FakeClock(START + timedelta(hours=3)))
        self.assertEqual(resumed.run.processed_count, 4)
        self.assertEqual(DailyCandidate.objects.filter(state="processed").count(), 25)

    def test_page_and_candidates_roll_back_together_on_checkpoint_failure(self) -> None:
        gateway = FakeGateway(
            new_releases=[_identity(1)],
            browse_pages={1: BrowsePage((_identity(2),), False)},
        )
        run_tick(gateway, FakeClock(START))
        with patch.object(DailyCycle, "save", side_effect=RuntimeError("checkpoint crash")):
            with self.assertRaisesMessage(RuntimeError, "checkpoint crash"):
                run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        self.assertEqual(DailyCandidate.objects.count(), 1)
        self.assertEqual(Game.objects.count(), 1)
        cycle = DailyCycle.objects.get()
        self.assertEqual((cycle.phase, cycle.browse_next_page), ("browse", 1))
        resumed = run_tick(gateway, FakeClock(START + timedelta(hours=2)))
        self.assertEqual(resumed.run.processed_count, 1)
        self.assertEqual(DailyCandidate.objects.filter(state="processed").count(), 2)

    def test_crash_after_discovery_commit_recovers_pending_batch_then_page_tail(self) -> None:
        gateway = FakeGateway(
            new_releases=[_identity(1)],
            browse_pages={1: BrowsePage(tuple(_identity(i) for i in range(2, 26)), False)},
        )
        run_tick(gateway, FakeClock(START))
        with patch("processing.selector.process_candidate", side_effect=RuntimeError("crash")):
            with self.assertRaisesMessage(RuntimeError, "crash"):
                run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        self.assertEqual(DailyCandidate.objects.filter(state="pending").count(), 20)
        with patch.object(gateway, "iter_browse", wraps=gateway.iter_browse) as browse:
            recovered = run_tick(gateway, FakeClock(START + timedelta(hours=2)))
        browse.assert_not_called()
        self.assertEqual(recovered.run.processed_count, 20)
        tail = run_tick(gateway, FakeClock(START + timedelta(hours=3)))
        self.assertEqual(tail.run.processed_count, 4)
        self.assertEqual(DailyCandidate.objects.filter(state="processed").count(), 25)

    def test_empty_nonterminal_page_stops_at_same_cursor(self) -> None:
        gateway = FakeGateway(new_releases=[], browse_pages={1: BrowsePage((), True)})
        run_tick(gateway, FakeClock(START))
        with patch.object(gateway, "iter_browse", wraps=gateway.iter_browse) as browse:
            result = run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        browse.assert_called_once_with(1)
        self.assertEqual(result.run.error_code, "browse_empty_page")
        self.assertEqual(result.outcome, "failed")
        cycle = DailyCycle.objects.get()
        self.assertEqual((cycle.phase, cycle.browse_next_page), ("browse", 1))

    def test_nonconsecutive_reordered_repetition_stops_after_saved_progress(self) -> None:
        gateway = FakeGateway(
            new_releases=[],
            browse_pages={
                1: BrowsePage((_identity(1), _identity(2)), True),
                2: BrowsePage((_identity(3),), True),
                3: BrowsePage((_identity(2), _identity(1)), True),
            },
        )
        run_tick(gateway, FakeClock(START))
        with patch.object(gateway, "iter_browse", wraps=gateway.iter_browse) as browse:
            result = run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        self.assertEqual(browse.call_count, 3)
        self.assertEqual(result.run.processed_count, 3)
        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.run.error_code, "browse_repeated_page")
        cycle = DailyCycle.objects.get()
        self.assertEqual((cycle.phase, cycle.browse_next_page), ("browse", 3))

    def test_page_budget_defers_distinct_known_pages_and_resumes(self) -> None:
        # 100 different subsets of seven already known games: valid overlapping pages with
        # no new candidate. They must be traversed without treating overlap as a loop.
        gateway = FakeGateway(
            new_releases=[_identity(i) for i in range(1, 8)],
            browse_pages={
                page: BrowsePage(
                    tuple(_identity(bit + 1) for bit in range(7) if page & (1 << bit)), True
                )
                for page in range(1, 101)
            },
        )
        gateway.browse_pages[101] = BrowsePage((_identity(8),), False)
        run_tick(gateway, FakeClock(START))
        with (
            patch("processing.selector.monotonic", return_value=0),
            patch.object(gateway, "iter_browse", wraps=gateway.iter_browse) as browse,
        ):
            result = run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        self.assertEqual(browse.call_count, 100)
        self.assertEqual(result.run.error_code, "browse_page_limit")
        self.assertEqual(result.outcome, "failed")
        cycle = DailyCycle.objects.get()
        self.assertEqual((cycle.phase, cycle.browse_next_page), ("browse", 101))
        resumed = run_tick(gateway, FakeClock(START + timedelta(hours=2)))
        self.assertEqual(resumed.run.processed_count, 1)
        self.assertEqual(DailyCycle.objects.get().phase, "exhausted")

    def test_elapsed_budget_stops_new_requests_but_commits_fetched_page(self) -> None:
        gateway = FakeGateway(
            new_releases=[],
            browse_pages={
                1: BrowsePage((_identity(1),), True),
                2: BrowsePage((_identity(2),), False),
            },
        )
        run_tick(gateway, FakeClock(START))
        with (
            patch("processing.selector.monotonic", side_effect=[0.0, 0.0, 60.0]),
            patch.object(gateway, "iter_browse", wraps=gateway.iter_browse) as browse,
        ):
            result = run_tick(gateway, FakeClock(START + timedelta(hours=1)))
        browse.assert_called_once_with(1)
        self.assertEqual(result.run.processed_count, 1)
        self.assertEqual(result.run.error_code, "browse_time_limit")
        self.assertEqual(result.outcome, "partial")
        cycle = DailyCycle.objects.get()
        self.assertEqual((cycle.phase, cycle.browse_next_page), ("browse", 2))
        resumed = run_tick(gateway, FakeClock(START + timedelta(hours=2)))
        self.assertEqual(resumed.run.processed_count, 1)
        self.assertEqual(DailyCycle.objects.get().phase, "exhausted")
