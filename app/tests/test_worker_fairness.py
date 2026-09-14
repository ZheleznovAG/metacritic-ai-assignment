"""IMP-04 R14: bounded service of both queues across worker restarts."""

from dataclasses import replace
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import httpx
from django.db import connection
from django.test import TestCase, TransactionTestCase
from reviews.management.commands.run_worker import Command
from summaries.models import SummaryJob

from tests.test_reviews_collector import FakeClock, FakeGateway, _make_job
from tests.test_reviews_snapshots import NOW, page
from tests.test_summary_admission import make_job, ok


class WorkerFairnessTests(TestCase):
    def setUp(self) -> None:
        self.review = _make_job()
        self.summary = make_job(2)
        self.clock = FakeClock(NOW)
        self.gateway = FakeGateway(
            {
                None: replace(page(1), reported_total=3, next_cursor="next"),
                "next": replace(page(2), reported_total=3, next_cursor="last"),
                "last": replace(page(3), reported_total=3),
            }
        )
        self.calls = 0

    def tick(self, api_key: str = "test-key") -> None:
        def reply(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return ok(request)

        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            Command(stdout=StringIO())._tick(
                self.gateway, client, self.clock, api_key, "https://api.groq.com/openai/v1"
            )

    def test_summary_gets_the_second_tick_despite_review_backlog_and_new_command_instance(
        self,
    ) -> None:
        self.tick()
        self.tick()
        self.review.refresh_from_db()
        self.summary.refresh_from_db()
        self.assertEqual(
            (self.review.page_count, self.summary.state, self.calls), (1, "succeeded", 1)
        )
        self.tick()
        self.review.refresh_from_db()
        self.assertEqual(self.review.page_count, 2)

    def test_missing_api_key_does_not_idle_on_a_summary_turn(self) -> None:
        self.tick(api_key="")
        self.tick(api_key="")
        self.review.refresh_from_db()
        self.summary.refresh_from_db()
        self.assertEqual(
            (self.review.page_count, self.summary.state, self.calls), (2, "pending", 0)
        )

    def test_not_due_summary_falls_through_to_review_work(self) -> None:
        SummaryJob.objects.filter(pk=self.summary.pk).update(available_at=NOW + timedelta(days=1))
        self.tick()
        self.tick()
        self.review.refresh_from_db()
        self.assertEqual(self.review.page_count, 2)
        self.assertEqual(self.calls, 0)

    def test_no_review_work_falls_through_to_summary_work(self) -> None:
        self.review.state = "failed"
        self.review.save(update_fields=["state"])
        self.tick()
        self.summary.refresh_from_db()
        self.assertEqual(self.summary.state, "succeeded")

    def test_delayed_summary_still_yields_the_next_turn_to_collection(self) -> None:
        self.tick()
        self.tick()
        another = make_job(3)
        self.tick()
        self.tick()
        another.refresh_from_db()
        self.assertEqual(another.state, "delayed_capacity")
        self.tick()
        self.review.refresh_from_db()
        self.assertEqual(self.review.state, "complete")


class DispatchTransactionTests(TransactionTestCase):
    def test_dispatch_lock_is_released_before_either_kind_of_http(self) -> None:
        _make_job()
        make_job(2)
        clock = FakeClock(NOW)
        gateway = FakeGateway({None: page(1)})
        original = gateway.fetch_review_page

        def review_reply(*args: object) -> object:
            self.assertFalse(connection.in_atomic_block)
            return original("critic", "g1", "pc", None)

        def summary_reply(request: httpx.Request) -> httpx.Response:
            self.assertFalse(connection.in_atomic_block)
            return ok(request)

        with patch.object(gateway, "fetch_review_page", side_effect=review_reply):
            with httpx.Client(transport=httpx.MockTransport(summary_reply)) as client:
                for _ in range(2):
                    Command(stdout=StringIO())._tick(
                        gateway, client, clock, "test-key", "https://api.groq.com/openai/v1"
                    )
        self.assertTrue(SummaryJob.objects.filter(state="succeeded").exists())
