"""`refresh_summaries`: corpora from an older selection policy are rebuilt from saved reviews and
their summaries enqueued, without Metacritic or provider calls."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from presentation.summaries import get_summaries
from reviews import collector
from reviews.management.commands.refresh_summaries import refresh
from reviews.models import ReviewCollectionJob, ReviewCorpus, ReviewCorpusHead
from reviews.selection import POLICY_VERSION
from summaries import contour, worker
from summaries.models import SummaryJob

from tests.test_reviews_collector import FakeClock, FakeGateway, _make_job
from tests.test_reviews_snapshots import NOW, next_job, page
from tests.test_summary_admission import ok, process

OLD_POLICY = "1.1.0-sentiment"


class RefreshSummariesTests(TestCase):
    def setUp(self) -> None:
        self.initial = _make_job()
        self.game = self.initial.game_platform.game
        self.clock = FakeClock(NOW)
        claim = collector.claim_next_job(self.clock)
        assert claim is not None
        collector.collect_one_page(FakeGateway({None: page(1, 2, 3)}), self.clock, claim)
        job = SummaryJob.objects.get()
        summary_claim = worker.claim_next_job(self.clock)
        assert summary_claim is not None
        process(summary_claim, self.clock, ok)
        # What an older release left behind: its corpus policy and its summary contour.
        ReviewCorpus.objects.update(policy_version=OLD_POLICY)
        SummaryJob.objects.filter(pk=job.pk).update(contour_fingerprint="old-contour")

    def critic_view_state(self) -> tuple[str, str | None]:
        view = next(v for v in get_summaries(self.game) if v.audience == "critic")
        return view.state, view.reason

    def test_an_outdated_corpus_is_rebuilt_and_its_summary_enqueued(self) -> None:
        self.assertEqual(self.critic_view_state(), ("stale", "contour_changed"))

        counts = refresh()

        self.assertEqual((counts.outdated, counts.rebuilt, counts.jobs_created), (1, 1, 1))
        head = ReviewCorpusHead.objects.get(game=self.game, audience="critic")
        self.assertEqual(head.corpus.policy_version, POLICY_VERSION)
        self.assertEqual(ReviewCorpus.objects.count(), 2)
        pending = SummaryJob.objects.get(contour_fingerprint=contour.contour_fingerprint())
        self.assertEqual((pending.state, pending.source_corpus_id), ("pending", head.corpus_id))
        # The old summary stays visible until the worker regenerates it.
        self.assertEqual(self.critic_view_state(), ("stale", "pending"))

    def test_a_second_run_enqueues_nothing(self) -> None:
        refresh()
        counts = refresh()
        self.assertEqual((counts.outdated, counts.rebuilt, counts.jobs_created), (0, 0, 0))
        self.assertEqual(SummaryJob.objects.count(), 2)

    def test_dry_run_writes_nothing(self) -> None:
        counts = refresh(dry_run=True)
        self.assertEqual((counts.heads, counts.outdated, counts.rebuilt), (1, 1, 0))
        self.assertEqual((ReviewCorpus.objects.count(), SummaryJob.objects.count()), (1, 1))

    def test_a_head_whose_latest_collection_is_incomplete_is_skipped(self) -> None:
        newer = next_job(self.initial, 13)
        ReviewCollectionJob.objects.filter(pk=newer.pk).update(state="retryable")

        counts = refresh()

        self.assertEqual(
            (counts.outdated, counts.skipped_incomplete, counts.jobs_created), (1, 1, 0)
        )
        self.assertEqual(ReviewCorpus.objects.count(), 1)

    def test_limit_bounds_the_rebuilds(self) -> None:
        self.assertEqual(refresh(limit=0).rebuilt, 0)
        self.assertEqual(ReviewCorpus.objects.count(), 1)

    def test_the_command_reports_its_counts(self) -> None:
        out = StringIO()
        call_command("refresh_summaries", "--dry-run", stdout=out)
        self.assertIn(f"policy={POLICY_VERSION} heads=1 outdated=1", out.getvalue())
