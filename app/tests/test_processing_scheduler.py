from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, TransactionTestCase
from metacritic.dto import BrowsePage, FetchEvidence, GameDTO, GameIdentityDTO, ReviewPageDTO
from processing.lease import LEASE_TTL, LeaseOverlap, acquire_lease
from processing.models import DailyCandidate, ProcessingLease, ProcessingRun
from processing.scheduler import current_slot, run_tick, trigger_key_for_slot

from tests.concurrency import run_concurrently


def _identity(n: int) -> GameIdentityDTO:
    return GameIdentityDTO(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=f"Game {n}"
    )


def _evidence(kind: str) -> FetchEvidence:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    return FetchEvidence(
        kind=kind,
        url="https://www.metacritic.com/x/",
        started_at=now,
        completed_at=now,
        http_status=200,
        response_sha256="a" * 64,
        parser_contract_version="1.0.0",
        outcome="succeeded",
        error_code=None,
    )


class FakeClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now_utc(self) -> datetime:
        return self.instant


class FakeGateway:
    def __init__(self, new_releases: list[GameIdentityDTO]) -> None:
        self.new_releases = new_releases
        self.calls = 0

    def list_new_releases(self) -> tuple[list[GameIdentityDTO] | None, FetchEvidence]:
        self.calls += 1
        return self.new_releases, _evidence("new_releases")

    def iter_browse(self, page: int) -> tuple[BrowsePage | None, FetchEvidence]:
        return BrowsePage(games=(), has_next_page=False), _evidence("browse_page")

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        n = int(url.rstrip("/").rsplit("/", 1)[-1][1:])
        identity = _identity(n)
        return (
            GameDTO(
                source_game_id=identity.source_game_id,
                canonical_locator=identity.canonical_locator,
                title=identity.title,
                cover_url=None,
                developer=None,
                description=None,
                video_embed_url=None,
                video_content_url=None,
                platforms=(),
            ),
            _evidence("game_detail"),
        )

    def fetch_platform_userscore(self, url: str) -> tuple[Decimal | None, FetchEvidence]:
        return None, _evidence("platform_userscore")

    def fetch_review_page(
        self, audience: str, game_slug: str, platform_slug: str, cursor: str | None
    ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
        return ReviewPageDTO(items=(), reported_total=0, next_cursor=None), _evidence("review_page")


class LeaseStealingGateway(FakeGateway):
    """Simulates another run legitimately reclaiming the (by-then-expired) lease after this
    run's Nth successful fetch — the same end state a real TTL expiry + re-acquisition would
    leave, without needing to fast-forward the clock past the 45-minute TTL for the test."""

    def __init__(self, new_releases: list[GameIdentityDTO], steal_after: int) -> None:
        super().__init__(new_releases)
        self._steal_after = steal_after
        self._fetches = 0

    def fetch_game(self, url: str) -> tuple[GameDTO | None, FetchEvidence]:
        result = super().fetch_game(url)
        self._fetches += 1
        if self._fetches == self._steal_after:
            from processing.lease import RESOURCE
            from processing.models import ProcessingLease

            thief = ProcessingRun.objects.create(
                trigger_key="scheduled:thief", scheduled_slot=result[1].started_at
            )
            lease = ProcessingLease.objects.get(resource=RESOURCE)
            lease.fencing_token += 1
            lease.owner_run = thief
            lease.save(update_fields=["fencing_token", "owner_run"])
        return result


class CurrentSlotTests(TestCase):
    def test_rounds_down_to_the_hour(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 37, 22, tzinfo=UTC))
        self.assertEqual(current_slot(clock), datetime(2026, 9, 11, 14, 0, tzinfo=UTC))

    def test_trigger_key_is_stable_for_the_whole_hour(self) -> None:
        slot = current_slot(FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC)))
        self.assertEqual(trigger_key_for_slot(slot), "scheduled:2026-09-11T14:00:00Z")


class RunTickTests(TestCase):
    def test_a_fresh_hour_creates_and_runs_a_new_processing_run(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        gateway = FakeGateway(new_releases=[_identity(1), _identity(2)])

        result = run_tick(gateway, clock)

        self.assertEqual(result.outcome, "succeeded")
        self.assertEqual(result.run.trigger_key, "scheduled:2026-09-11T14:00:00Z")
        self.assertEqual(result.run.processed_count, 2)
        self.assertEqual(gateway.calls, 1)

    def test_a_repeat_tick_in_the_same_hour_does_not_fetch_again(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        gateway = FakeGateway(new_releases=[_identity(1)])

        run_tick(gateway, clock)
        second = run_tick(gateway, clock)

        self.assertEqual(second.outcome, "skipped_duplicate")
        self.assertEqual(gateway.calls, 1)  # no new HTTP work for the duplicate tick
        self.assertEqual(ProcessingRun.objects.count(), 1)
        self.assertEqual(DailyCandidate.objects.count(), 1)

    def test_the_next_hour_is_a_new_independent_run(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        gateway = FakeGateway(new_releases=[_identity(1)])
        run_tick(gateway, clock)

        clock.instant = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
        gateway.new_releases = []  # phase is already "browse" after the first run
        second = run_tick(gateway, clock)

        self.assertNotEqual(second.run.trigger_key, "scheduled:2026-09-11T14:00:00Z")
        self.assertEqual(second.run.trigger_key, "scheduled:2026-09-11T15:00:00Z")
        self.assertEqual(ProcessingRun.objects.count(), 2)

    def test_a_lease_lost_mid_batch_backfills_accurate_counters_from_committed_attempts(
        self,
    ) -> None:
        # candidate 1's own fetch succeeds and commits before the token is bumped; candidate 2's
        # fetch is the one that bumps it, so candidate 2's own commit detects the stale token.
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        gateway = LeaseStealingGateway(new_releases=[_identity(1), _identity(2)], steal_after=2)

        result = run_tick(gateway, clock)

        self.assertEqual(result.outcome, "partial")
        self.assertEqual(result.run.status, "partial")
        self.assertEqual(result.run.error_code, "lease_expired")
        self.assertEqual(result.run.processed_count, 1)
        self.assertEqual(result.run.failed_count, 0)  # candidate 2 never reached a terminal attempt
        self.assertEqual(DailyCandidate.objects.get(game__source_game_id="g1").state, "processed")
        # candidate 2 is left mid-flight ("processing"), exactly as a real crash would leave it;
        # the next run's recovery step (PS-08) is what converts it to retryable.
        self.assertEqual(DailyCandidate.objects.get(game__source_game_id="g2").state, "processing")


class AbandonedRunRecoveryTests(TestCase):
    """HRD-02 / A05: a run that never reached its own final save (crashed between creating the
    row and acquiring the lease, or crashed mid-batch after acquiring it) must not permanently
    strand that hour's work behind `skipped_duplicate`."""

    def test_a_run_abandoned_before_lease_acquisition_is_resumed_in_the_same_hour(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        slot = current_slot(clock)
        # Exactly what the original `create()` call leaves behind if the process crashes before
        # ever reaching `acquire_lease` — no fencing_token, no business_day, no started_at.
        stranded = ProcessingRun.objects.create(
            trigger_key=trigger_key_for_slot(slot), scheduled_slot=slot, status="queued"
        )
        gateway = FakeGateway(new_releases=[_identity(1)])

        result = run_tick(gateway, clock)

        self.assertEqual(result.outcome, "succeeded")
        self.assertEqual(result.run.pk, stranded.pk)
        self.assertEqual(result.run.processed_count, 1)
        self.assertEqual(ProcessingRun.objects.count(), 1)
        self.assertEqual(gateway.calls, 1)

    def test_a_run_abandoned_mid_batch_is_resumed_once_its_lease_has_expired(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        slot = current_slot(clock)
        crashed = ProcessingRun.objects.create(
            trigger_key=trigger_key_for_slot(slot),
            scheduled_slot=slot,
            business_day=slot.date(),
            status="running",
            started_at=slot,
        )
        with transaction.atomic():
            token = acquire_lease(clock, crashed)
        crashed.fencing_token = token
        crashed.save(update_fields=["fencing_token"])
        # Simulate the crash: nothing calls release_lease, so the lease is left held until its
        # TTL naturally expires. Advance past that TTL but stay in the same hour slot.
        clock.instant = slot + LEASE_TTL + timedelta(minutes=5)
        gateway = FakeGateway(new_releases=[_identity(1)])

        result = run_tick(gateway, clock)

        self.assertEqual(result.outcome, "succeeded")
        self.assertEqual(result.run.pk, crashed.pk)
        self.assertEqual(result.run.business_day, slot.date())  # preserved, not reset on resume
        self.assertEqual(result.run.started_at, slot)  # preserved, not reset on resume
        self.assertEqual(result.run.processed_count, 1)
        self.assertEqual(ProcessingRun.objects.count(), 1)

    def test_a_still_live_run_is_reported_duplicate_without_its_row_being_touched(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        slot = current_slot(clock)
        live = ProcessingRun.objects.create(
            trigger_key=trigger_key_for_slot(slot),
            scheduled_slot=slot,
            business_day=slot.date(),
            status="running",
            started_at=slot,
        )
        with transaction.atomic():
            token = acquire_lease(clock, live)
        live.fencing_token = token
        live.save(update_fields=["fencing_token"])
        # No time advance: the lease is still genuinely valid, as it would be for a real
        # concurrently-running process, not a crashed one.
        gateway = FakeGateway(new_releases=[_identity(1)])

        result = run_tick(gateway, clock)

        self.assertEqual(result.outcome, "skipped_duplicate")
        self.assertEqual(result.run.pk, live.pk)
        self.assertEqual(gateway.calls, 0)  # the resume attempt never touched the gateway
        self.assertEqual(ProcessingRun.objects.count(), 1)
        live.refresh_from_db()
        self.assertEqual(live.status, "running")  # untouched — still owned by the "live" process
        lease = ProcessingLease.objects.get(resource="ingestion")
        self.assertEqual(lease.owner_run_id, live.pk)
        self.assertEqual(lease.fencing_token, token)

    def test_a_run_that_finished_between_the_lookup_and_the_resume_attempt_reports_its_real_outcome(
        self,
    ) -> None:
        # A concurrent resumer can close the row for real (a genuine "succeeded" run, not a
        # crash) in the window between this tick's initial unlocked read of `existing` and its
        # own `_try_resume` attempt. The reported TickResult must reflect that real outcome, not
        # the stale in-memory snapshot taken before the race.
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        slot = current_slot(clock)
        stranded = ProcessingRun.objects.create(
            trigger_key=trigger_key_for_slot(slot), scheduled_slot=slot, status="queued"
        )

        def fake_try_resume(run_id: int, gateway: object, tick_clock: object) -> None:
            # Simulate the concurrent winner: it finishes and commits a real terminal outcome
            # with real counts, then this loser's own resume attempt correctly finds nothing
            # left to resume (`_try_resume`'s own row-lock re-check would return None here).
            ProcessingRun.objects.filter(pk=run_id).update(
                status="succeeded", processed_count=3, failed_count=0, selected_count=3
            )
            return None

        with patch("processing.scheduler._try_resume", side_effect=fake_try_resume):
            result = run_tick(FakeGateway(new_releases=[]), clock)

        self.assertEqual(result.run.pk, stranded.pk)
        self.assertEqual(result.run.status, "succeeded")
        self.assertEqual(result.run.processed_count, 3)
        self.assertEqual(result.outcome, "skipped_duplicate")


class LeaseAcquisitionRaceTests(TransactionTestCase):
    """HRD-03: the sequential/`FakeClock` coverage above proves the resume/reclaim *logic* is
    correct given a known interleaving; it never proves the underlying `select_for_update()` lock
    actually serializes two genuinely concurrent PostgreSQL transactions, since `TestCase` wraps
    every test in one connection/transaction where real concurrency cannot occur. These use real
    threads with their own DB connections, synchronized with a `threading.Barrier` so both call
    `acquire_lease` at (as close as the OS scheduler allows to) the same instant."""

    def test_two_real_threads_racing_for_the_same_lease_resource_never_both_win(self) -> None:
        clock = FakeClock(datetime(2026, 9, 11, 14, 0, tzinfo=UTC))
        slot = current_slot(clock)
        # Pre-create the singleton row so the race under test is purely the acquisition itself
        # (select_for_update + owner assignment), not get_or_create's own separately-covered
        # first-ever-row creation race.
        ProcessingLease.objects.create(resource="ingestion")
        first_run, second_run = (
            ProcessingRun.objects.create(
                trigger_key=f"scheduled:race-{i}", scheduled_slot=slot, status="running"
            )
            for i in range(2)
        )

        def attempt(run: ProcessingRun) -> int | None:
            try:
                with transaction.atomic():
                    return acquire_lease(clock, run)
            except LeaseOverlap:
                return None

        def attempt_first() -> int | None:
            return attempt(first_run)

        def attempt_second() -> int | None:
            return attempt(second_run)

        tokens, errors = run_concurrently(attempt_first, attempt_second)

        self.assertEqual(errors, [], f"acquire_lease raised under real concurrency: {errors}")
        winners = [token for token in tokens if token is not None]
        self.assertEqual(len(winners), 1, f"exactly one racer must win the lease, got {tokens}")
        lease = ProcessingLease.objects.get(resource="ingestion")
        self.assertEqual(lease.fencing_token, winners[0])
        winner_run = first_run if tokens[0] is not None else second_run
        self.assertEqual(lease.owner_run_id, winner_run.pk)
