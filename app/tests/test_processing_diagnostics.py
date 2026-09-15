import hashlib
from datetime import UTC, datetime
from io import StringIO

from catalog.models import Game, GamePlatform
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from processing import diagnostics
from processing.models import DailyCandidate, DailyCycle, ProcessingRun
from reviews.models import ReviewCollectionJob, ReviewCorpus
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


def _make_platform(game: Game, n: int = 1) -> GamePlatform:
    return GamePlatform.objects.create(
        game=game,
        source_platform_id=f"p{n}",
        source_game_platform_id=f"gp{n}",
        slug="pc",
        name="PC",
    )


def _make_corpus(game: Game, audience: str) -> ReviewCorpus:
    return ReviewCorpus.objects.create(
        game=game,
        audience=audience,
        policy_version="1.0.0-candidate",
        source_set_fingerprint=hashlib.sha256(f"fp-{game.id}-{audience}".encode()).hexdigest(),
        model_input_fingerprint=hashlib.sha256(f"input-{game.id}-{audience}".encode()).hexdigest(),
        complete_route_count=1,
        empty_route_count=0,
        reported_count=3,
        fetched_count=3,
        unique_count=3,
        deduplicated_count=0,
        selected_count=3,
        tokenizer_id="o200k_harmony",
        tokenizer_version="0.14.0",
        raw_prompt_tokens=100,
        guarded_prompt_tokens=164,
        completion_reservation=800,
    )


def _make_summary_job(game: Game, audience: str, **overrides: object) -> SummaryJob:
    corpus = _make_corpus(game, audience)
    defaults: dict[str, object] = {
        "game": game,
        "audience": audience,
        "source_corpus": corpus,
        "input_fingerprint": corpus.model_input_fingerprint,
        "contour_fingerprint": hashlib.sha256(b"contour").hexdigest(),
    }
    defaults.update(overrides)
    return SummaryJob.objects.create(**defaults)


class RunDiagnosticsTests(TestCase):
    def test_reports_status_error_and_counts(self) -> None:
        run = ProcessingRun.objects.create(
            trigger_key="scheduled:2026-09-12T10:00:00Z",
            scheduled_slot=datetime(2026, 9, 12, 10, tzinfo=UTC),
            business_day=datetime(2026, 9, 12, tzinfo=UTC).date(),
            status="partial",
            error_code="lease_expired",
            started_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
            ended_at=datetime(2026, 9, 12, 10, 5, tzinfo=UTC),
            selected_count=3,
            processed_count=1,
            failed_count=0,
        )

        result = diagnostics.run_diagnostics(run.id)

        assert result is not None
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["error_code"], "lease_expired")
        self.assertEqual(result["selected_count"], 3)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["started_at"], "2026-09-12T10:00:00Z")

    def test_unknown_run_id_is_none(self) -> None:
        self.assertIsNone(diagnostics.run_diagnostics(999999))


class GameDiagnosticsTests(TestCase):
    def test_reports_last_success_and_every_jobs_own_state(self) -> None:
        game = _make_game(1)
        platform = _make_platform(game)
        yesterday = DailyCycle.objects.create(business_date="2026-09-11")
        today = DailyCycle.objects.create(business_date="2026-09-12")
        DailyCandidate.objects.create(cycle=yesterday, game=game, source_order=1, state="processed")
        today_candidate = DailyCandidate.objects.create(
            cycle=today, game=game, source_order=1, state="retryable", last_error="http_500"
        )
        ReviewCollectionJob.objects.create(
            daily_candidate=today_candidate,
            game_platform=platform,
            audience="critic",
            state="failed",
            last_error="attempt_limit",
        )
        _make_summary_job(game, "critic", state="succeeded")

        result = diagnostics.game_diagnostics(game.id)

        assert result is not None
        self.assertEqual(result["latest_candidate_state"], "retryable")
        self.assertEqual(result["latest_candidate_last_error"], "http_500")
        self.assertEqual(result["last_success_business_date"], "2026-09-11")
        self.assertEqual(len(result["review_jobs"]), 1)
        self.assertEqual(result["review_jobs"][0]["state"], "failed")
        self.assertEqual(result["review_jobs"][0]["last_error"], "attempt_limit")
        self.assertEqual(len(result["summary_jobs"]), 1)
        self.assertEqual(result["summary_jobs"][0]["state"], "succeeded")

    def test_unknown_game_id_is_none(self) -> None:
        self.assertIsNone(diagnostics.game_diagnostics(999999))


class JobDiagnosticsTests(TestCase):
    def test_review_job_reports_progress_and_error(self) -> None:
        game = _make_game(2)
        platform = _make_platform(game)
        cycle = DailyCycle.objects.create(business_date="2026-09-12")
        candidate = DailyCandidate.objects.create(cycle=cycle, game=game, source_order=1)
        job = ReviewCollectionJob.objects.create(
            daily_candidate=candidate,
            game_platform=platform,
            audience="user",
            state="retryable",
            last_error="http_500",
            fetched_count=10,
            unique_count=9,
        )

        result = diagnostics.job_diagnostics("review", job.id)

        assert result is not None
        self.assertEqual(result["game_id"], game.id)
        self.assertEqual(result["state"], "retryable")
        self.assertEqual(result["fetched_count"], 10)
        self.assertEqual(result["unique_count"], 9)

    def test_summary_job_reports_state_and_error(self) -> None:
        game = _make_game(3)
        job = _make_summary_job(
            game, "critic", state="delayed_capacity", last_error="quota_exhausted"
        )

        result = diagnostics.job_diagnostics("summary", job.id)

        assert result is not None
        self.assertEqual(result["game_id"], game.id)
        self.assertEqual(result["state"], "delayed_capacity")
        self.assertEqual(result["last_error"], "quota_exhausted")

    def test_unknown_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            diagnostics.job_diagnostics("bogus", 1)

    def test_unknown_job_id_is_none(self) -> None:
        self.assertIsNone(diagnostics.job_diagnostics("review", 999999))
        self.assertIsNone(diagnostics.job_diagnostics("summary", 999999))


class BacklogDiagnosticsTests(TestCase):
    def test_counts_outstanding_work_by_stage(self) -> None:
        game = _make_game(4)
        platform = _make_platform(game)
        cycle = DailyCycle.objects.create(business_date="2026-09-12")
        candidate = DailyCandidate.objects.create(
            cycle=cycle, game=game, source_order=1, state="pending"
        )
        second_game = _make_game(5)
        DailyCandidate.objects.create(
            cycle=cycle, game=second_game, source_order=2, state="processed"
        )
        ReviewCollectionJob.objects.create(
            daily_candidate=candidate, game_platform=platform, audience="critic", state="pending"
        )
        third_game = _make_game(6)
        third_platform = _make_platform(third_game, 3)
        stuck_candidate = DailyCandidate.objects.create(
            cycle=cycle, game=third_game, source_order=3, state="processing"
        )
        ReviewCollectionJob.objects.create(
            daily_candidate=stuck_candidate,
            game_platform=third_platform,
            audience="critic",
            state="unstable",
            last_error="review_changed_during_collection",
        )
        clock = FakeClock(datetime(2026, 9, 12, 12, tzinfo=UTC))

        result = diagnostics.backlog_diagnostics(clock)

        self.assertEqual(result["daily_candidates_by_state"]["pending"], 1)
        self.assertEqual(result["daily_candidates_by_state"]["processed"], 1)
        self.assertEqual(result["review_jobs_by_state"]["pending"], 1)
        # A stuck "unstable" job stays diagnosable here, not silently excluded by a filter that
        # only shows a subset of "in-flight" states (reviews/collector.py: such a job "stays
        # visible and diagnosable", never auto-restarted).
        self.assertEqual(result["review_jobs_by_state"]["unstable"], 1)
        self.assertEqual(result["summary_backlog"]["arrivals"], 0)


class DiagnoseCommandTests(TestCase):
    def test_run_flag_prints_json_to_stdout(self) -> None:
        run = ProcessingRun.objects.create(
            trigger_key="scheduled:x",
            scheduled_slot=datetime(2026, 9, 12, tzinfo=UTC),
            status="succeeded",
        )
        out = StringIO()
        call_command("diagnose", "--run", str(run.id), stdout=out)
        self.assertIn(f'"run_id": {run.id}', out.getvalue())
        self.assertIn('"status": "succeeded"', out.getvalue())

    def test_unknown_run_id_raises_command_error(self) -> None:
        with self.assertRaises(CommandError):
            call_command("diagnose", "--run", "999999", stdout=StringIO())

    def test_backlog_flag_prints_json(self) -> None:
        out = StringIO()
        call_command("diagnose", "--backlog", stdout=out)
        self.assertIn("summary_backlog", out.getvalue())
