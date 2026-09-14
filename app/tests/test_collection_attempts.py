"""IMP-04 R08/R11: page retries, durable HTTP intents and claim redelivery."""

import threading
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from catalog.models import SourceFetch
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from metacritic.dto import FetchEvidence, ReviewPageDTO
from reviews import collector
from reviews.models import ReviewCollectionJob, ReviewCorpus, ReviewObservation

from tests.test_reviews_collector import FakeClock, FakeGateway, _make_job
from tests.test_reviews_snapshots import NOW, page


class CollectionAttemptTests(TestCase):
    def setUp(self) -> None:
        self.job = _make_job()
        self.clock = FakeClock(NOW)

    def claim(self) -> ReviewCollectionJob:
        claim = collector.claim_next_job(self.clock)
        assert claim is not None
        return claim

    def test_six_successful_pages_do_not_consume_the_next_page_retry_budget(self) -> None:
        for i in range(6):
            claim = self.claim()
            collector.collect_one_page(
                FakeGateway(
                    {
                        claim.next_cursor: replace(
                            page(i), reported_total=7, next_cursor=f"cursor-{i + 1}"
                        )
                    }
                ),
                self.clock,
                claim,
            )
        failed = collector.collect_one_page(FakeGateway({}), self.clock, self.claim())
        self.assertEqual(failed.state, "retryable")
        self.assertEqual(failed.available_at, NOW + timedelta(minutes=1))
        self.clock.instant += timedelta(minutes=1)
        final = collector.collect_one_page(
            FakeGateway({"cursor-6": replace(page(6), reported_total=7)}), self.clock, self.claim()
        )
        self.assertEqual((final.state, final.page_count, final.attempt_count), ("complete", 7, 8))
        self.assertEqual(ReviewObservation.objects.count(), 7)

    def test_each_page_has_five_attempts_even_after_previous_retries(self) -> None:
        for _ in range(4):
            collector.collect_one_page(FakeGateway({}), self.clock, self.claim())
            self.clock.instant += timedelta(days=1)
        collector.collect_one_page(
            FakeGateway({None: replace(page(1), reported_total=2, next_cursor="next")}),
            self.clock,
            self.claim(),
        )
        for i in range(5):
            result = collector.collect_one_page(FakeGateway({}), self.clock, self.claim())
            self.assertEqual(result.state, "failed" if i == 4 else "retryable")
            self.clock.instant += timedelta(days=1)
        self.assertIsNone(collector.claim_next_job(self.clock))
        self.assertEqual(SourceFetch.objects.count(), 10)

    def test_terminal_redelivery_has_no_http_and_preserves_terminal_page(self) -> None:
        claim = self.claim()
        gateway = FakeGateway({None: page(1)})
        collector.collect_one_page(gateway, self.clock, claim)
        before = list(SourceFetch.objects.values())
        collector.collect_one_page(gateway, self.clock, claim)
        self.job.refresh_from_db()
        self.assertEqual(gateway.calls, [None])
        self.assertEqual(list(SourceFetch.objects.values()), before)
        self.assertEqual(self.job.state, "complete")

    def test_inflight_redelivery_does_not_send_a_second_http(self) -> None:
        claim = self.claim()
        gateway = FakeGateway({None: page(1)})
        duplicate = FakeGateway({})
        original = gateway.fetch_review_page

        def during(
            audience: str, game_slug: str, platform_slug: str, cursor: str | None
        ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
            collector.collect_one_page(duplicate, self.clock, claim)
            return original(audience, game_slug, platform_slug, cursor)

        with patch.object(gateway, "fetch_review_page", side_effect=during):
            collector.collect_one_page(gateway, self.clock, claim)
        self.assertEqual(duplicate.calls, [])
        self.assertEqual(SourceFetch.objects.count(), 1)

    def test_expired_claim_without_reclaim_sends_nothing(self) -> None:
        claim = self.claim()
        self.clock.instant += collector.LEASE_TTL
        gateway = FakeGateway({None: page(1)})
        collector.collect_one_page(gateway, self.clock, claim)
        self.assertEqual(gateway.calls, [])
        self.assertFalse(SourceFetch.objects.exists())

    def test_http_intent_is_durable_and_five_crashes_exhaust_this_page(self) -> None:
        for attempt_no in range(1, 6):
            claim = self.claim()

            def crash(
                *args: object, number: int = attempt_no, token: int = claim.fencing_token
            ) -> None:
                saved = SourceFetch.objects.get(outcome="started")
                self.assertEqual(saved.attempt_no, number)
                self.assertEqual(saved.fencing_token, token)
                self.assertIn("/critic/games/g1/platform/pc/", saved.url)
                raise SystemExit("simulated process death")

            with patch.object(FakeGateway, "fetch_review_page", side_effect=crash):
                with self.assertRaises(SystemExit):
                    collector.collect_one_page(FakeGateway({}), self.clock, claim)
            self.clock.instant += collector.LEASE_TTL
        self.assertIsNone(collector.claim_next_job(self.clock))
        self.assertEqual(SourceFetch.objects.filter(outcome="abandoned").count(), 5)
        self.job.refresh_from_db()
        self.assertEqual((self.job.state, self.job.attempt_count), ("failed", 5))

    def test_late_old_response_cannot_rewrite_abandoned_or_winning_attempt(self) -> None:
        old = self.claim()
        gateway = FakeGateway({None: page(1, suffix="old")})
        original = gateway.fetch_review_page
        history: list[object] = []

        def during(
            audience: str, game_slug: str, platform_slug: str, cursor: str | None
        ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
            self.clock.instant += collector.LEASE_TTL
            winner = self.claim()
            collector.collect_one_page(
                FakeGateway({None: page(2, suffix="new")}), self.clock, winner
            )
            history.extend(SourceFetch.objects.order_by("id").values())
            return original(audience, game_slug, platform_slug, cursor)

        with patch.object(gateway, "fetch_review_page", side_effect=during):
            collector.collect_one_page(gateway, self.clock, old)
        self.assertEqual(list(SourceFetch.objects.order_by("id").values()), history)
        self.assertEqual(
            list(ReviewCorpus.objects.get().items.values_list("review__identity_key", flat=True)),
            ["id:2"],
        )

    def test_generation_or_cursor_changes_invalidate_the_inmemory_claim(self) -> None:
        claim = self.claim()
        ReviewCollectionJob.objects.filter(pk=claim.pk).update(
            collection_generation=1, next_cursor="changed"
        )
        gateway = FakeGateway({None: page(1)})
        collector.collect_one_page(gateway, self.clock, claim)
        self.assertEqual(gateway.calls, [])
        self.assertFalse(SourceFetch.objects.exists())


class CollectionIntentTransactionTests(TransactionTestCase):
    def test_intent_is_visible_from_another_connection_before_http_returns(self) -> None:
        _make_job()
        clock = FakeClock(NOW)
        claim = collector.claim_next_job(clock)
        assert claim is not None
        gateway = FakeGateway({None: page(1)})
        original = gateway.fetch_review_page
        observed: list[str] = []
        errors: list[Exception] = []

        def read_other_connection() -> None:
            try:
                observed.append(SourceFetch.objects.get(review_job=claim).outcome)
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()

        def during(
            audience: str, game_slug: str, platform_slug: str, cursor: str | None
        ) -> tuple[ReviewPageDTO | None, FetchEvidence]:
            self.assertFalse(connection.in_atomic_block)
            thread = threading.Thread(target=read_other_connection)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(observed, ["started"])
            return original(audience, game_slug, platform_slug, cursor)

        with patch.object(gateway, "fetch_review_page", side_effect=during):
            collector.collect_one_page(gateway, clock, claim)
        self.assertEqual(SourceFetch.objects.get().outcome, "succeeded")
