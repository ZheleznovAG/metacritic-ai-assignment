from datetime import UTC, datetime, timedelta

from catalog.models import Game
from django.test import TestCase
from reviews.models import ReviewCorpus
from summaries import observability
from summaries.models import SummaryJob


class FakeClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now_utc(self) -> datetime:
        return self.instant


def _make_game(n: int) -> Game:
    return Game.objects.create(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=f"Game {n}"
    )


def _make_corpus(game: Game, tag: str) -> ReviewCorpus:
    return ReviewCorpus.objects.create(
        game=game,
        audience="critic",
        policy_version="1.0.0-candidate",
        source_set_fingerprint=f"fp-{tag}",
        model_input_fingerprint=f"input-{tag}",
        complete_route_count=1,
        empty_route_count=0,
        reported_count=5,
        fetched_count=5,
        unique_count=5,
        deduplicated_count=0,
        selected_count=5,
        tokenizer_id="o200k_harmony",
        tokenizer_version="0.14.0",
        raw_prompt_tokens=50,
        guarded_prompt_tokens=114,
        completion_reservation=800,
    )


class BacklogSnapshotTests(TestCase):
    def test_counts_arrivals_completed_and_outstanding_separately(self) -> None:
        game = _make_game(1)
        for tag, state in (("a", "pending"), ("b", "succeeded"), ("c", "retryable")):
            SummaryJob.objects.create(
                game=game,
                audience="critic",
                source_corpus=_make_corpus(game, tag),
                input_fingerprint=f"fp-{tag}",
                contour_fingerprint="cf1",
                state=state,
            )

        snapshot = observability.backlog_snapshot(
            FakeClock(datetime(2026, 9, 12, 12, 0, tzinfo=UTC))
        )

        self.assertEqual(snapshot.arrivals, 3)
        self.assertEqual(snapshot.completed, 1)
        self.assertEqual(snapshot.outstanding, 2)

    def test_oldest_outstanding_age_reflects_the_earliest_arrival(self) -> None:
        game = _make_game(2)
        job = SummaryJob.objects.create(
            game=game,
            audience="critic",
            source_corpus=_make_corpus(game, "old"),
            input_fingerprint="fp-old",
            contour_fingerprint="cf1",
            state="pending",
        )
        SummaryJob.objects.filter(pk=job.pk).update(
            created_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
        )

        snapshot = observability.backlog_snapshot(
            FakeClock(datetime(2026, 9, 12, 10, 30, tzinfo=UTC))
        )

        self.assertEqual(
            snapshot.oldest_outstanding_age_seconds, timedelta(minutes=30).total_seconds()
        )

    def test_no_outstanding_jobs_reports_no_age(self) -> None:
        snapshot = observability.backlog_snapshot(
            FakeClock(datetime(2026, 9, 12, 12, 0, tzinfo=UTC))
        )
        self.assertIsNone(snapshot.oldest_outstanding_age_seconds)
