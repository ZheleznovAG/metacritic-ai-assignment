"""SPK-04 paper scenarios (PS-01..12) against a FakeClock and a fake gateway.

PS-11 ("AI failure doesn't revert core") is IMP-04 territory; in this codebase it reduces to
"ReviewCollectionJob state never touches DailyCandidate", true by construction — see
EnrichmentIndependenceTests below rather than a simulated AI failure. PS-12 (non-UTC business
timezone) is not built: ASM-01's default (UTC) is what ships; DailyCycle.timezone exists in the
schema but nothing reconfigures it yet, so the timezone-boundary test below only exercises the UTC
midnight boundary.
"""

from datetime import UTC, datetime
from decimal import Decimal

from catalog.models import Game
from django.db import transaction
from django.test import TestCase
from metacritic.dto import BrowsePage, FetchEvidence, GameDTO, GameIdentityDTO, ReviewPageDTO
from processing.lease import LeaseOverlap, acquire_lease, current_fencing_token
from processing.models import DailyCandidate, DailyCycle, ProcessingRun
from processing.scheduler import run_tick
from processing.selector import BATCH_LIMIT, run_batch
from reviews.models import ReviewCollectionJob


def _identity(n: int) -> GameIdentityDTO:
    return GameIdentityDTO(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=f"Game {n}"
    )


def _game_dto(n: int) -> GameDTO:
    identity = _identity(n)
    return GameDTO(
        source_game_id=identity.source_game_id,
        canonical_locator=identity.canonical_locator,
        title=identity.title,
        cover_url=None,
        developer=None,
        description=None,
        video_embed_url=None,
        video_content_url=None,
        platforms=(),
    )


def _evidence(kind: str, outcome: str = "succeeded") -> FetchEvidence:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    return FetchEvidence(
        kind=kind,
        url="https://www.metacritic.com/x/",
        started_at=now,
        completed_at=now,
        http_status=200 if outcome == "succeeded" else 503,
        response_sha256="a" * 64 if outcome == "succeeded" else None,
        parser_contract_version="1.0.0",
        outcome=outcome,
        error_code=None if outcome == "succeeded" else "http_503",
    )


class FakeClock:
    def __init__(self, *instants: datetime) -> None:
        self._instants = list(instants)
        self._last = instants[0] if instants else datetime(2026, 9, 11, tzinfo=UTC)

    def now_utc(self) -> datetime:
        if self._instants:
            self._last = self._instants.pop(0)
        return self._last


class FakeGateway:
    def __init__(
        self,
        new_releases: list[GameIdentityDTO] | None = None,
        browse_pages: dict[int, BrowsePage] | None = None,
        failing_pages: set[int] | None = None,
        failing_games: set[str] | None = None,
    ) -> None:
        self.new_releases = new_releases
        self.browse_pages = browse_pages or {}
        self.failing_pages = failing_pages or set()
        self.failing_games = failing_games or set()

    def list_new_releases(self) -> tuple[list[GameIdentityDTO] | None, FetchEvidence]:
        if self.new_releases is None:
            return None, _evidence("new_releases", outcome="failed")
        return self.new_releases, _evidence("new_releases")

    def iter_browse(self, page: int) -> tuple[BrowsePage | None, FetchEvidence]:
        if page in self.failing_pages:
            return None, _evidence("browse_page", outcome="failed")
        result = self.browse_pages.get(page)
        if result is None:
            return BrowsePage(games=(), has_next_page=False), _evidence("browse_page")
        return result, _evidence("browse_page")

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug in self.failing_games:
            return None, _evidence("game_detail", outcome="failed")
        n = int(slug[1:])
        return _game_dto(n), _evidence("game_detail")

    def fetch_platform_userscore(self, url: str) -> tuple[Decimal | None, FetchEvidence]:
        return None, _evidence("platform_userscore")

    def fetch_review_page(
        self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
    ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
        return ReviewPageDTO(items=(), reported_total=0, next_cursor=None), _evidence("review_page")


def _make_run(clock: FakeClock, business_day: datetime, token: int) -> ProcessingRun:
    run = ProcessingRun.objects.create(
        trigger_key=f"scheduled:{business_day.isoformat()}",
        scheduled_slot=business_day,
        business_day=business_day.date(),
        fencing_token=token,
        status="running",
        started_at=business_day,
    )
    return run


def _cycle_for(run: ProcessingRun) -> DailyCycle:
    assert run.business_day is not None
    return DailyCycle.objects.get(business_date=run.business_day)


def _acquire(run: ProcessingRun, clock: FakeClock) -> int:
    with transaction.atomic():
        token = acquire_lease(clock, run)
    run.fencing_token = token
    run.save(update_fields=["fencing_token"])
    return token


class FirstRunTests(TestCase):
    def test_ps01_first_run_takes_up_to_twenty_new_releases_only(self) -> None:
        clock = FakeClock(datetime(2026, 9, 4, 9, 0, tzinfo=UTC))
        run = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run, clock)
        gateway = FakeGateway(new_releases=[_identity(n) for n in range(1, 26)])

        result = run_batch(gateway, clock, run)

        self.assertEqual(result.selected_count, BATCH_LIMIT)
        self.assertEqual(result.processed_count, BATCH_LIMIT)
        self.assertEqual(result.status, "succeeded")
        cycle = _cycle_for(run)
        self.assertEqual(cycle.phase, "browse")
        self.assertEqual(DailyCandidate.objects.filter(cycle=cycle).count(), 20)
        self.assertEqual(
            set(
                DailyCandidate.objects.filter(cycle=cycle).values_list(
                    "game__source_game_id", flat=True
                )
            ),
            {f"g{n}" for n in range(1, 21)},
        )


class SubsequentRunTests(TestCase):
    def _seed_first_twenty(self, clock: FakeClock) -> ProcessingRun:
        run = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run, clock)
        gateway = FakeGateway(new_releases=[_identity(n) for n in range(1, 21)])
        run_batch(gateway, clock, run)
        return run

    def test_ps02_subsequent_pages_skip_processed_and_advance_cursor(self) -> None:
        clock = FakeClock(
            datetime(2026, 9, 4, 9, 0, tzinfo=UTC), datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
        )
        self._seed_first_twenty(clock)

        run2 = _make_run(clock, datetime(2026, 9, 4, 10, 0, tzinfo=UTC), 1)
        _acquire(run2, clock)
        gateway = FakeGateway(
            browse_pages={
                1: BrowsePage(games=tuple(_identity(n) for n in range(15, 26)), has_next_page=True),
                2: BrowsePage(games=tuple(_identity(n) for n in range(26, 41)), has_next_page=True),
            }
        )

        result = run_batch(gateway, clock, run2)

        self.assertEqual(result.selected_count, 20)
        self.assertEqual(result.processed_count, 20)
        cycle = _cycle_for(run2)
        self.assertEqual(cycle.browse_next_page, 3)
        new_ids = set(
            DailyCandidate.objects.filter(cycle=cycle, source_order__gt=20).values_list(
                "game__source_game_id", flat=True
            )
        )
        self.assertEqual(new_ids, {f"g{n}" for n in range(21, 41)})

    def test_ac_sel06_exhaustion_ends_the_run_with_zero_new_candidates(self) -> None:
        clock = FakeClock(
            datetime(2026, 9, 4, 9, 0, tzinfo=UTC), datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
        )
        run1 = self._seed_first_twenty(clock)
        cycle = _cycle_for(run1)
        cycle.phase = "exhausted"
        cycle.save(update_fields=["phase"])

        run2 = _make_run(clock, datetime(2026, 9, 4, 10, 0, tzinfo=UTC), 1)
        _acquire(run2, clock)
        gateway = FakeGateway()  # no list calls expected to matter; phase is exhausted

        result = run_batch(gateway, clock, run2)

        self.assertEqual(result.selected_count, 0)
        self.assertEqual(result.processed_count, 0)
        self.assertEqual(result.status, "succeeded")


class ItemFailureTests(TestCase):
    def test_ps03_item_failure_is_retryable_without_backfill_then_retried_first(self) -> None:
        clock = FakeClock(
            datetime(2026, 9, 4, 9, 0, tzinfo=UTC), datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
        )
        run1 = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run1, clock)
        gateway1 = FakeGateway(
            new_releases=[_identity(n) for n in range(41, 61)], failing_games={"g47"}
        )

        result1 = run_batch(gateway1, clock, run1)

        self.assertEqual(result1.selected_count, 20)
        self.assertEqual(result1.processed_count, 19)
        self.assertEqual(result1.failed_count, 1)
        self.assertEqual(result1.status, "partial")
        failed = DailyCandidate.objects.get(game__source_game_id="g47")
        self.assertEqual(failed.state, "retryable")

        cycle = _cycle_for(run1)
        run2 = _make_run(clock, datetime(2026, 9, 4, 10, 0, tzinfo=UTC), 1)
        _acquire(run2, clock)
        gateway2 = FakeGateway(
            browse_pages={
                1: BrowsePage(games=tuple(_identity(n) for n in range(61, 80)), has_next_page=True)
            }
        )

        result2 = run_batch(gateway2, clock, run2)

        self.assertEqual(result2.selected_count, 20)  # g47 retry + 19 new, not 20 new
        failed.refresh_from_db()
        self.assertEqual(failed.state, "processed")
        self.assertEqual(cycle.pk, _cycle_for(run1).pk)

    def test_a_batch_where_every_item_fails_is_a_failed_run_not_partial(self) -> None:
        # processing-state.md's Run status table: "no progress ... or all core items failed" is
        # `failed`, not `partial` — distinct from PS-03 above, where only one of several items
        # fails and real progress was still made.
        clock = FakeClock(datetime(2026, 9, 4, 9, 0, tzinfo=UTC))
        run = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run, clock)
        gateway = FakeGateway(
            new_releases=[_identity(1), _identity(2)],
            failing_games={"g1", "g2"},
        )

        result = run_batch(gateway, clock, run)

        self.assertEqual(result.selected_count, 2)
        self.assertEqual(result.processed_count, 0)
        self.assertEqual(result.failed_count, 2)
        self.assertEqual(result.status, "failed")


class NewDayTests(TestCase):
    def test_ps04_new_day_updates_existing_game_without_duplicate_and_keeps_old_cycle(self) -> None:
        clock = FakeClock(
            datetime(2026, 9, 4, 9, 0, tzinfo=UTC), datetime(2026, 9, 5, 0, 5, tzinfo=UTC)
        )
        run1 = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run1, clock)
        run_batch(FakeGateway(new_releases=[_identity(1)]), clock, run1)
        old_cycle = _cycle_for(run1)
        self.assertEqual(Game.objects.filter(source_game_id="g1").count(), 1)

        run2 = _make_run(clock, datetime(2026, 9, 5, 0, 5, tzinfo=UTC), 1)
        _acquire(run2, clock)
        result = run_batch(FakeGateway(new_releases=[_identity(1), _identity(61)]), clock, run2)

        self.assertEqual(result.selected_count, 2)
        self.assertEqual(Game.objects.filter(source_game_id="g1").count(), 1)  # no duplicate
        self.assertEqual(Game.objects.filter(source_game_id="g61").count(), 1)
        new_cycle = _cycle_for(run2)
        self.assertNotEqual(old_cycle.pk, new_cycle.pk)
        self.assertTrue(DailyCycle.objects.filter(pk=old_cycle.pk).exists())  # not deleted
        self.assertTrue(
            DailyCandidate.objects.filter(cycle=new_cycle, game__source_game_id="g1").exists()
        )


class MidnightCrossingTests(TestCase):
    def test_ps05_run_started_before_midnight_keeps_its_business_day_throughout(self) -> None:
        # The clock advances past midnight mid-run; business_day was fixed at acquisition.
        clock = FakeClock(
            datetime(2026, 9, 4, 23, 59, tzinfo=UTC), datetime(2026, 9, 5, 0, 3, tzinfo=UTC)
        )
        run = _make_run(clock, datetime(2026, 9, 4, 23, 59, tzinfo=UTC), 0)
        _acquire(run, clock)

        result = run_batch(FakeGateway(new_releases=[_identity(1), _identity(2)]), clock, run)

        self.assertEqual(result.processed_count, 2)
        cycle = DailyCandidate.objects.get(game__source_game_id="g1").cycle
        self.assertEqual(cycle.business_date.isoformat(), "2026-09-04")


class NextPageFailureTests(TestCase):
    def test_ps09_a_failed_next_page_does_not_advance_the_cursor_past_it(self) -> None:
        clock = FakeClock(
            datetime(2026, 9, 4, 9, 0, tzinfo=UTC), datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
        )
        run1 = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run1, clock)
        run_batch(FakeGateway(new_releases=[_identity(n) for n in range(1, 21)]), clock, run1)

        run2 = _make_run(clock, datetime(2026, 9, 4, 10, 0, tzinfo=UTC), 1)
        _acquire(run2, clock)
        gateway = FakeGateway(
            browse_pages={
                1: BrowsePage(games=tuple(_identity(n) for n in range(21, 29)), has_next_page=True)
            },
            failing_pages={2},
        )

        result = run_batch(gateway, clock, run2)

        self.assertEqual(result.processed_count, 8)
        self.assertEqual(result.status, "partial")
        cycle = _cycle_for(run2)
        self.assertEqual(cycle.browse_next_page, 2)  # not advanced past the failed page


class RestartRecoveryTests(TestCase):
    def test_ps08_a_candidate_left_processing_by_a_crash_becomes_retryable(self) -> None:
        # The second instant is >45 minutes after the first, so the never-released lease from
        # run1 (simulating a crash — nothing called release_lease) has genuinely expired by the
        # time run2 tries to acquire it, per the lease TTL (docs/design.md).
        clock = FakeClock(
            datetime(2026, 9, 4, 9, 0, tzinfo=UTC), datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
        )
        run1 = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run1, clock)
        run_batch(FakeGateway(new_releases=[_identity(1)]), clock, run1)
        stuck = DailyCandidate.objects.get(game__source_game_id="g1")
        stuck.state = "processing"
        stuck.save(update_fields=["state"])

        run2 = _make_run(clock, datetime(2026, 9, 4, 10, 0, tzinfo=UTC), 1)
        _acquire(run2, clock)
        run_batch(FakeGateway(new_releases=[]), clock, run2)

        stuck.refresh_from_db()
        self.assertEqual(stuck.state, "processed")  # retried and succeeded this run


class LeaseOverlapTests(TestCase):
    def test_ps06_overlapping_trigger_is_rejected_while_the_lease_is_held(self) -> None:
        clock = FakeClock(datetime(2026, 9, 4, 9, 0, tzinfo=UTC))
        holder = ProcessingRun.objects.create(
            trigger_key="scheduled:holder", scheduled_slot=datetime(2026, 9, 4, 9, 0, tzinfo=UTC)
        )
        with transaction.atomic():
            acquire_lease(clock, holder)

        latecomer = ProcessingRun.objects.create(
            trigger_key="scheduled:latecomer",
            scheduled_slot=datetime(2026, 9, 4, 9, 0, tzinfo=UTC),
        )
        with self.assertRaises(LeaseOverlap):
            with transaction.atomic():
                acquire_lease(clock, latecomer)
        self.assertEqual(current_fencing_token(), 1)


class DuplicateTriggerTests(TestCase):
    def test_ps07_the_same_hour_slot_is_idempotent(self) -> None:
        clock = FakeClock(
            datetime(2026, 9, 4, 9, 0, 5, tzinfo=UTC), datetime(2026, 9, 4, 9, 0, 5, tzinfo=UTC)
        )
        gateway = FakeGateway(new_releases=[_identity(1)])

        first = run_tick(gateway, clock)
        second = run_tick(gateway, clock)

        self.assertEqual(second.outcome, "skipped_duplicate")
        self.assertEqual(first.run.id, second.run.id)
        self.assertEqual(ProcessingRun.objects.count(), 1)
        self.assertEqual(DailyCandidate.objects.count(), 1)


class EnrichmentIndependenceTests(TestCase):
    def test_a_candidate_stays_processed_regardless_of_its_review_jobs_state(self) -> None:
        # PS-11's point, applied to this codebase: ReviewCollectionJob.state (IMP-04's future AI
        # enrichment outcome) has no signal path back to DailyCandidate — a future AI failure
        # literally cannot revert a processed candidate, because nothing ever writes candidate
        # state from a job. Proven directly: driving every job to "failed" changes nothing here.
        clock = FakeClock(datetime(2026, 9, 4, 9, 0, tzinfo=UTC))
        run = _make_run(clock, datetime(2026, 9, 4, 9, 0, tzinfo=UTC), 0)
        _acquire(run, clock)
        run_batch(FakeGateway(new_releases=[_identity(1)]), clock, run)
        candidate = DailyCandidate.objects.get(game__source_game_id="g1")
        self.assertEqual(candidate.state, "processed")

        ReviewCollectionJob.objects.filter(daily_candidate=candidate).update(state="failed")

        candidate.refresh_from_db()
        self.assertEqual(candidate.state, "processed")
