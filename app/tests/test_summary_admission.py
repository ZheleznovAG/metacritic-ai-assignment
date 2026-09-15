"""IMP-04 R01/R09/R10: actual HTTP payload, atomic quota and durable attempts."""

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import timedelta
from unittest.mock import patch

import httpx
import tiktoken
from django.db import connections
from django.test import TestCase, TransactionTestCase
from reviews.selection import truncate_to_token_boundary
from summaries import contour, quota, worker
from summaries.models import SummaryAttempt, SummaryJob

from tests.test_reviews_collector import FakeClock
from tests.test_reviews_snapshots import NOW
from tests.test_summaries_worker import (
    _make_corpus,
    _make_game,
    _make_platform,
    _make_review,
    _ok_response,
)


def make_job(n: int = 1, *, maximum: bool = False) -> SummaryJob:
    game = _make_game(n)
    platform = _make_platform(game)
    reviews = [_make_review(platform, "critic", i) for i in range(10 if maximum else 3)]
    if maximum:
        seeds = (
            "Combat and exploration are rewarding. ",
            "Исследовать мир интересно. ",
            "探索过程很有吸引力。",
            "🎮 Precise controls 🌍 ",
        )
        for i, review in enumerate(reviews):
            review.text_original = truncate_to_token_boundary(seeds[i % len(seeds)] * 500)
            review.save(update_fields=["text_original"])
    return worker.ensure_job(_make_corpus(game, "critic", reviews))


def ok(request: httpx.Request, **headers: str) -> httpx.Response:
    payload = json.loads(request.content)
    user = json.loads(payload["messages"][1]["content"])
    return httpx.Response(
        200, json=_ok_response(user["case_id"], user["audience"]), headers=headers
    )


def process(
    job: SummaryJob, clock: FakeClock, handler: Callable[[httpx.Request], httpx.Response]
) -> SummaryJob:
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return worker.process_job(
            client, clock, job, api_key="test-key", base_url="https://api.groq.com/openai/v1"
        )


class SummaryAdmissionTests(TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(NOW)

    def claim(self) -> SummaryJob:
        job = worker.claim_next_job(self.clock)
        assert job is not None
        return job

    def test_full_maximum_payload_is_measured_and_reserved_before_http(self) -> None:
        make_job(maximum=True)
        claim = self.claim()
        encoding = tiktoken.get_encoding("o200k_harmony")

        def inspect(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            canonical_input = contour.canonical_json(
                {"messages": payload["messages"], "response_format": payload["response_format"]}
            )
            raw = len(encoding.encode(canonical_input, disallowed_special=()))
            saved = SummaryAttempt.objects.get(job=claim)
            self.assertIsNone(saved.outcome)
            self.assertEqual(saved.raw_prompt_tokens, raw)
            self.assertEqual(saved.estimated_prompt_tokens, raw + 64)
            self.assertEqual(saved.reserved_total_tokens, raw + 64 + 800)
            self.assertLessEqual(saved.estimated_prompt_tokens, 6000)
            self.assertEqual(
                saved.request_sha256,
                hashlib.sha256(contour.canonical_json(payload).encode()).hexdigest(),
            )
            self.assertEqual(saved.fencing_token, claim.fencing_token)
            self.assertEqual(saved.request_sha256, hashlib.sha256(request.content).hexdigest())
            user = json.loads(payload["messages"][1]["content"])
            self.assertEqual(len(user["reviews"]), 10)
            self.assertTrue(
                all(
                    len(encoding.encode(item["text"], disallowed_special=())) == 450
                    for item in user["reviews"]
                )
            )
            return ok(request)

        self.assertEqual(process(claim, self.clock, inspect).state, "succeeded")

    def test_oversized_complete_payload_fails_without_http_or_reservation(self) -> None:
        make_job()
        with patch("summaries.contour.load_system_prompt", return_value="excessive " * 7000):
            updated = process(self.claim(), self.clock, lambda _: self.fail("oversized HTTP"))
        self.assertEqual((updated.state, updated.last_error), ("failed", "prompt_budget_exceeded"))
        self.assertEqual(SummaryAttempt.objects.count(), 0)

    def test_tokenizer_failure_is_closed_before_http(self) -> None:
        make_job()
        with patch("summaries.preflight.count_tokens", side_effect=RuntimeError("no tokenizer")):
            updated = process(self.claim(), self.clock, lambda _: self.fail("unmeasured HTTP"))
        self.assertEqual((updated.state, updated.last_error), ("failed", "tokenizer_unavailable"))
        self.assertEqual(SummaryAttempt.objects.count(), 0)

    def test_each_http_retry_gets_a_separate_durable_attempt(self) -> None:
        make_job()
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            self.assertEqual(SummaryAttempt.objects.count(), len(calls))
            return httpx.Response(503) if len(calls) == 1 else ok(request)

        with patch("summaries.groq_adapter.time.sleep"):
            first = process(self.claim(), self.clock, handler)
        self.assertEqual((first.state, len(calls)), ("retryable", 1))
        self.clock.instant += timedelta(minutes=2)
        second = process(self.claim(), self.clock, handler)
        self.assertEqual((second.state, len(calls)), ("succeeded", 2))
        self.assertEqual(
            list(
                SummaryAttempt.objects.order_by("attempt_no").values_list("attempt_no", "outcome")
            ),
            [(1, "retryable"), (2, "succeeded")],
        )

    def test_reclaim_abandons_a_crashed_attempt_and_creates_a_new_one(self) -> None:
        make_job()

        def crash(_: httpx.Request) -> httpx.Response:
            raise SystemExit("worker died during HTTP")

        with self.assertRaises(SystemExit):
            process(self.claim(), self.clock, crash)
        self.clock.instant += worker.LEASE_TTL + timedelta(seconds=1)
        claim = self.claim()
        old = SummaryAttempt.objects.get()
        self.assertEqual(old.outcome, "abandoned")
        self.assertIsNotNone(old.completed_at)
        self.assertEqual(process(claim, self.clock, ok).state, "succeeded")
        old.refresh_from_db()
        self.assertEqual(old.outcome, "abandoned")
        self.assertEqual(SummaryAttempt.objects.count(), 2)

    def test_late_response_cannot_rewrite_an_abandoned_attempt_or_new_summary(self) -> None:
        make_job()

        def late(request: httpx.Request) -> httpx.Response:
            self.clock.instant += worker.LEASE_TTL + timedelta(seconds=1)
            process(self.claim(), self.clock, ok)
            return ok(request)

        process(self.claim(), self.clock, late)
        self.assertEqual(
            list(SummaryAttempt.objects.order_by("attempt_no").values_list("outcome", flat=True)),
            ["abandoned", "succeeded"],
        )
        successful = SummaryJob.objects.get().summary.successful_attempt
        assert successful is not None
        self.assertEqual(successful.attempt_no, 2)

    def test_completed_claim_redelivery_makes_no_new_http_or_attempt(self) -> None:
        make_job()
        claim = self.claim()
        process(claim, self.clock, ok)
        process(claim, self.clock, lambda _: self.fail("duplicate HTTP"))
        self.assertEqual(SummaryAttempt.objects.count(), 1)
        self.assertEqual(SummaryJob.objects.get().state, "succeeded")

    def test_expired_claim_without_reclaim_cannot_send_or_reserve(self) -> None:
        make_job()
        claim = self.claim()
        self.clock.instant += worker.LEASE_TTL
        process(claim, self.clock, lambda _: self.fail("expired HTTP"))
        self.assertEqual(SummaryAttempt.objects.count(), 0)

    def test_missing_headers_delays_the_next_request_until_a_minute_after_response(self) -> None:
        make_job()
        make_job(2)
        process(self.claim(), self.clock, ok)
        self.assertLess(SummaryAttempt.objects.get().reserved_total_tokens * 2, quota.FREE_TPM)
        updated = process(self.claim(), self.clock, lambda _: self.fail("unconfirmed headroom"))
        self.assertEqual(
            (updated.state, updated.available_at), ("delayed_capacity", NOW + timedelta(minutes=1))
        )
        self.clock.instant += timedelta(minutes=1)
        self.assertEqual(process(self.claim(), self.clock, ok).state, "succeeded")

    def test_provider_zero_tokens_respects_the_reported_reset(self) -> None:
        make_job()
        make_job(2)
        process(
            self.claim(),
            self.clock,
            lambda request: ok(
                request,
                **{
                    "x-ratelimit-remaining-tokens": "0",
                    "x-ratelimit-reset-tokens": "2m0s",
                    "x-ratelimit-remaining-requests": "999",
                    "x-ratelimit-reset-requests": "1d",
                },
            ),
        )
        updated = process(self.claim(), self.clock, lambda _: self.fail("provider reset bypassed"))
        self.assertEqual(updated.available_at, NOW + timedelta(minutes=2))
        self.clock.instant += timedelta(minutes=1)
        self.assertIsNone(worker.claim_next_job(self.clock))
        self.clock.instant += timedelta(minutes=1)
        self.assertEqual(process(self.claim(), self.clock, ok).state, "succeeded")

    def test_daily_token_limit_survives_a_minute_reset(self) -> None:
        make_job()
        make_job(2)
        process(self.claim(), self.clock, ok)
        reserved = SummaryAttempt.objects.get().reserved_total_tokens
        self.clock.instant += timedelta(minutes=2)
        with patch("summaries.quota.FREE_TPD", reserved):
            updated = process(self.claim(), self.clock, lambda _: self.fail("daily token limit"))
        self.assertEqual(updated.available_at, NOW + timedelta(days=1))

    def test_request_limits_apply_in_requests_independently_of_tokens(self) -> None:
        make_job()
        make_job(2)
        headers = {
            "x-ratelimit-remaining-tokens": "8000",
            "x-ratelimit-reset-tokens": "1m",
            "x-ratelimit-remaining-requests": "1000",
            "x-ratelimit-reset-requests": "1d",
        }
        process(self.claim(), self.clock, lambda request: ok(request, **headers))
        with patch("summaries.quota.FREE_RPM", 1):
            updated = process(self.claim(), self.clock, lambda _: self.fail("RPM exceeded"))
        self.assertEqual(updated.available_at, NOW + timedelta(minutes=1))
        self.clock.instant += timedelta(minutes=2)
        with patch("summaries.quota.FREE_RPD", 1):
            updated = process(self.claim(), self.clock, lambda _: self.fail("RPD exceeded"))
        self.assertEqual(updated.available_at, NOW + timedelta(days=1))

    def test_nan_retry_after_uses_a_finite_delay(self) -> None:
        make_job()
        updated = process(
            self.claim(), self.clock, lambda _: httpx.Response(429, headers={"Retry-After": "NaN"})
        )
        self.assertEqual(
            (updated.state, updated.available_at), ("delayed_capacity", NOW + timedelta(minutes=1))
        )

    def test_five_transport_failures_stop_automatic_http(self) -> None:
        make_job()
        for index in range(5):
            updated = process(self.claim(), self.clock, lambda _: httpx.Response(503))
            if index < 4:
                assert updated.available_at is not None
                self.clock.instant = updated.available_at
        self.assertEqual(updated.state, "failed")
        self.assertIsNone(worker.claim_next_job(self.clock))
        self.assertEqual(SummaryAttempt.objects.count(), 5)

    def test_provider_usage_above_guard_halts_further_calls_for_this_contour(self) -> None:
        make_job()
        make_job(2)

        def excessive(request: httpx.Request) -> httpx.Response:
            response = ok(request).json()
            response["usage"] = {
                "prompt_tokens": 9000,
                "completion_tokens": 20,
                "total_tokens": 9020,
            }
            return httpx.Response(200, json=response)

        result = process(self.claim(), self.clock, excessive)
        self.assertEqual((result.state, result.last_error), ("failed", "usage_exceeds_budget"))
        self.clock.instant += timedelta(minutes=2)
        result = process(self.claim(), self.clock, lambda _: self.fail("budget halt bypassed"))
        self.assertEqual(result.last_error, "usage_budget_halted")


class ConcurrentQuotaTests(TransactionTestCase):
    def test_two_connections_cannot_reserve_more_than_the_minute_budget(self) -> None:
        make_job(1, maximum=True)
        make_job(2, maximum=True)
        clock = FakeClock(NOW)
        claims = [worker.claim_next_job(clock), worker.claim_next_job(clock)]
        start = threading.Barrier(2)
        both_checked = threading.Event()
        checked_lock = threading.Lock()
        checked = 0
        calls: list[httpx.Request] = []
        errors: list[BaseException] = []
        has_capacity = quota.has_capacity

        def competing_check(clock: FakeClock, amount: int) -> bool:
            nonlocal checked
            result = has_capacity(clock, amount)
            with checked_lock:
                checked += 1
                if checked == 2:
                    both_checked.set()
            both_checked.wait(timeout=0.3)
            return result

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertFalse(connections["default"].in_atomic_block)
            calls.append(request)
            return ok(request)

        def run(index: int) -> None:
            try:
                start.wait(timeout=5)
                claim = claims[index]
                assert claim is not None
                process(claim, clock, handler)
            except BaseException as error:  # noqa: BLE001
                errors.append(error)
            finally:
                connections.close_all()

        with patch("summaries.quota.has_capacity", side_effect=competing_check):
            threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(SummaryJob.objects.filter(state="delayed_capacity").count(), 1)
        self.assertLessEqual(
            sum(SummaryAttempt.objects.values_list("reserved_total_tokens", flat=True)),
            quota.FREE_TPM,
        )
