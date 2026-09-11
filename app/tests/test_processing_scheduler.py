from datetime import UTC, datetime
from decimal import Decimal

from django.test import TestCase
from metacritic.dto import BrowsePage, FetchEvidence, GameDTO, GameIdentityDTO
from processing.models import DailyCandidate, ProcessingRun
from processing.scheduler import current_slot, run_tick, trigger_key_for_slot


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
