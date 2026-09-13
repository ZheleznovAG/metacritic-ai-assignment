"""Current review of 6551e42; synthetic data in Django's test DB only.

Assertions deliberately confirm the observed defects, not the desired behavior.
Run: .\.venv-app\Scripts\python.exe -B research/reviews/6551e42/reproduce.py
No external HTTP calls; existing repository fakes are used for setup.
"""
import os
import sys
import json
from pathlib import Path
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env.app", override=False)
assert os.environ.get("APP_ENV") != "production"
os.environ["POSTGRES_DB"] += "_checks"
os.environ["DATABASE_USER"] = os.environ["CHECKS_DB_USER"]
os.environ["DATABASE_PASSWORD"] = os.environ["CHECKS_DB_PASSWORD"]
os.environ["APP_ENV"] = "test"
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
import django
django.setup()
import httpx
from django.test import TestCase, TransactionTestCase
from django.test.runner import DiscoverRunner
from django.db import connections, transaction
from django.db.models import Sum
from catalog.models import Game, SourceFetch
from processing.models import DailyCycle, DailyCandidate
from processing.scheduler import run_tick
from metacritic.dto import ReviewPageDTO, BrowsePage
from reviews import collector, corpus as corpora
from reviews.models import ReviewCollectionJob, ReviewCorpus, ReviewObservation
from reviews.selection import count_tokens, truncate_to_token_boundary
from summaries import worker, quota, contour, groq_adapter
from summaries.models import SummaryAttempt, ReviewSummary, SummaryJob
from presentation.summaries import get_summaries
from reviews.management.commands.run_worker import Command
from tests import test_reviews_collector as rc
from tests import test_summaries_worker as sw
from tests import test_presentation_summaries as ps
from tests import test_processing_selector as sel

NOW = datetime(2026, 9, 13, 10, tzinfo=UTC)

def report(name, **facts):
    print("OBSERVATION " + json.dumps({"name": name, **facts}, sort_keys=True), flush=True)

def next_daily_job(old, day=14):
    cycle = DailyCycle.objects.create(business_date=f"2026-09-{day}")
    candidate = DailyCandidate.objects.create(cycle=cycle, game=old.game_platform.game,
                                               source_order=1, state="processed")
    return ReviewCollectionJob.objects.create(daily_candidate=candidate,
               game_platform=old.game_platform, audience=old.audience)

def page3(suffix=""):
    return ReviewPageDTO(items=tuple(replace(rc._item(i, source_review_id=str(i)),
                  text=f"Review {i} has useful observations {suffix}") for i in range(3)),
                         reported_total=3, next_cursor=None)

def collect(page, clock=None):
    clock = clock or rc.FakeClock(NOW)
    return collector.collect_one_page(rc.FakeGateway({None: page}), clock,
                                     collector.claim_next_job(clock))

def summary_job(n):
    game = sw._make_game(n)
    platform = sw._make_platform(game)
    reviews = [sw._make_review(platform, "critic", i) for i in range(3)]
    return worker.ensure_job(sw._make_corpus(game, "critic", reviews))

def response_for_request(request):
    payload = json.loads(request.content)
    data = json.loads(payload["messages"][1]["content"])
    return sw._ok_response(data["case_id"], data["audience"])

class ReviewProbes(TestCase):
    def test_01_page_tails_fixed(self):
        gateway = sel.FakeGateway(new_releases=[sel._identity(1)], browse_pages={
            1: BrowsePage(games=tuple(sel._identity(i) for i in range(2,26)), has_next_page=True),
            2: BrowsePage(games=tuple(sel._identity(i) for i in range(26,50)), has_next_page=False)})
        counts = []
        for hour in range(5):
            counts.append(run_tick(gateway, rc.FakeClock(NOW + timedelta(hours=hour))).run.processed_count)
        self.assertEqual(Game.objects.count(), 49)
        self.assertEqual(counts, [1, 20, 20, 8, 0])
        self.assertEqual(DailyCycle.objects.get().phase, "exhausted")
        report("page_tails_FIXED", expected_games=49, actual_games=49, processed_per_tick=counts)

    def test_02_unchanged_daily_collection_is_unstable(self):
        initial = rc._make_job()
        self.assertEqual(collect(page3()).state, "complete")
        next_daily_job(initial)
        second = collect(page3())
        self.assertEqual((second.state, second.unique_count), ("unstable", 0))
        self.assertEqual(second.observations.count(), 3)
        report("repeat_collection", state=second.state, unique=second.unique_count,
               observations=second.observations.count())

    def test_03_changed_text_reuses_old_corpus(self):
        initial = rc._make_job()
        collect(page3("old"))
        old = ReviewCorpus.objects.get()
        next_daily_job(initial)
        self.assertEqual(collect(page3("new")).state, "complete")
        current = corpora.build(initial.game_platform.game, "critic")
        self.assertEqual(current.pk, old.pk)
        self.assertTrue(all("old" in item.input_text for item in current.items.all()))
        report("edited_text", corpus_reused=True, model_input_still_old=True)

    def test_04_pending_generation_pollutes_complete_corpus(self):
        initial = rc._make_job()
        collect(page3())
        next_daily_job(initial)
        partial = ReviewPageDTO(items=(rc._item(4, source_review_id="4"),),
                               reported_total=4, next_cursor="next")
        collect(partial)
        current = corpora.build(initial.game_platform.game, "critic")
        self.assertEqual((current.reported_count, current.unique_count), (3,4))
        report("partial_pollution", reported=current.reported_count, unique=current.unique_count)

    def test_05_handoff_crash_loses_summary_job(self):
        initial = rc._make_job()
        with patch.object(collector, "_maybe_build_corpus_and_summary_job", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                collect(page3())
        initial.refresh_from_db()
        self.assertEqual(initial.state, "complete")
        self.assertIsNone(collector.claim_next_job(rc.FakeClock(NOW + timedelta(days=1))))
        self.assertEqual(SummaryJob.objects.count(), 0)
        report("handoff_crash", collection=initial.state, summary_jobs=0, reclaimable=False)

    def test_06_first_failure_after_successful_pages_is_terminal(self):
        rc._make_job()
        clock = rc.FakeClock(NOW)
        pages = {None if i == 0 else str(i): ReviewPageDTO(
            items=(rc._item(i),), reported_total=6, next_cursor=str(i+1)) for i in range(5)}
        gateway = rc.FakeGateway(pages)
        for _ in range(6):
            result = collector.collect_one_page(gateway, clock, collector.claim_next_job(clock))
        self.assertEqual((result.page_count, result.state), (5, "failed"))
        report("page_retry_budget", successful_pages=5, failures=1, state=result.state)

    def test_07_unknown_support_is_published_as_success(self):
        job = summary_job(7)
        def reply(request):
            response = response_for_request(request)
            output = json.loads(response["choices"][0]["message"]["content"])
            output["likes"][0]["support"] = ["R99"]
            response["choices"][0]["message"]["content"] = json.dumps(output)
            return httpx.Response(200, json=response)
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            result = worker.process_job(client, rc.FakeClock(NOW), worker.claim_next_job(rc.FakeClock(NOW)),
                         api_key="fake", base_url=groq_adapter.DEFAULT_BASE_URL)
        self.assertEqual(result.state, "succeeded")
        self.assertEqual(job.summary.claims.count(), 0)
        report("unknown_support", state=result.state, claims=0)

    def test_08_new_collection_is_not_shown_stale(self):
        initial = rc._make_job()
        collect(page3())
        job = SummaryJob.objects.get()
        job.state = "succeeded"
        job.save()
        ReviewSummary.objects.create(job=job, status="ok", generated_at=NOW,
                                     canonical_output_fingerprint="ok")
        next_daily_job(initial)
        view = get_summaries(initial.game_platform.game)[0]
        self.assertEqual(view.state, "ok")
        report("collection_staleness", newer_collection="pending", displayed=view.state)

    def test_09_equal_corpus_timestamps_select_old_summary(self):
        game = ps._make_game(9)
        old, new = [ps._make_corpus(game, "critic", tag) for tag in ("old", "new")]
        ReviewCorpus.objects.filter(game=game).update(created_at=NOW)
        job = SummaryJob.objects.create(game=game, audience="critic", source_corpus=old,
                     input_fingerprint="old", contour_fingerprint="old", state="succeeded")
        ReviewSummary.objects.create(job=job, status="ok", generated_at=NOW,
                                      canonical_output_fingerprint="ok")
        SummaryJob.objects.create(game=game, audience="critic", source_corpus=new,
                     input_fingerprint="new", contour_fingerprint="new", state="retryable")
        self.assertEqual(get_summaries(game)[0].state, "ok")
        report("timestamp_tie", newer_summary_job="retryable", displayed="ok")

    def test_10_accepted_claim_redelivery_changes_terminal_state(self):
        initial = rc._make_job()
        clock = rc.FakeClock(NOW)
        claim = collector.claim_next_job(clock)
        gateway = rc.FakeGateway({None: page3()})
        first = collector.collect_one_page(gateway, clock, claim)
        self.assertEqual(first.state, "complete")
        second = collector.collect_one_page(gateway, clock, claim)
        self.assertEqual(second.state, "unstable")
        self.assertEqual(len(gateway.calls), 2)
        report("redelivery", before="complete", after=second.state, http_calls=2)

    def test_11_hidden_provider_retries_share_one_attempt(self):
        summary_job(11)
        count = 0
        def reply(request):
            nonlocal count
            count += 1
            if count <= 3:
                return httpx.Response(503, json={"error": {"code": "unavailable"}})
            return httpx.Response(200, json=response_for_request(request))
        with httpx.Client(transport=httpx.MockTransport(reply)) as client, patch.object(groq_adapter.time, "sleep"):
            worker.process_job(client, rc.FakeClock(NOW), worker.claim_next_job(rc.FakeClock(NOW)),
                                api_key="fake", base_url=groq_adapter.DEFAULT_BASE_URL)
        self.assertEqual((count, SummaryAttempt.objects.count()), (4,1))
        report("hidden_http_retries", actual_http_calls=count, persisted_attempts=1,
               reserved_tokens=SummaryAttempt.objects.get().reserved_total_tokens)

    def test_12_review_work_starves_ready_summary(self):
        from io import StringIO
        rc._make_job()
        job = summary_job(12)
        pages = {None if i == 0 else str(i): ReviewPageDTO(items=(rc._item(i),),
                  reported_total=1000, next_cursor=str(i+1)) for i in range(30)}
        command = Command(stdout=StringIO())
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,
                     json=response_for_request(request)))) as client:
            for _ in range(30):
                command._tick(rc.FakeGateway(pages), client, rc.FakeClock(NOW), "fake",
                              groq_adapter.DEFAULT_BASE_URL)
        self.assertEqual(SummaryAttempt.objects.count(), 0)
        self.assertEqual(SummaryJob.objects.get(pk=job.pk).state, "pending")
        report("worker_fairness", successful_review_ticks=30, summary_attempts=0,
               capacity_available=quota.has_capacity(rc.FakeClock(NOW), 6800))

    def test_13_payload_can_exceed_declared_token_ceiling(self):
        text = truncate_to_token_boundary("\\" * 4000)
        reviews = [{"id": f"R{i:02d}", "text": text} for i in range(1,11)]
        payload = contour.build_request_payload("summary-job-13", "user", reviews)
        serialized = contour.canonical_json({"messages": payload["messages"],
                                             "response_format": payload["response_format"]})
        actual = count_tokens(serialized) + 64
        self.assertGreater(actual, 6000)
        rc._make_job(audience="user")
        page = ReviewPageDTO(items=tuple(replace(rc._item(i, source_review_id=str(i)),
                 text="\\" * 4000) for i in range(10)), reported_total=10, next_cursor=None)
        collect(page)
        observed = []
        def reply(request):
            sent = json.loads(request.content)
            observed.append(count_tokens(contour.canonical_json({
                "messages": sent["messages"], "response_format": sent["response_format"]})) + 64)
            return httpx.Response(200, json=response_for_request(request))
        clock = rc.FakeClock(NOW)
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            worker.process_job(client, clock, worker.claim_next_job(clock), api_key="fake",
                               base_url=groq_adapter.DEFAULT_BASE_URL)
        self.assertGreater(observed[0], 6000)
        report("token_ceiling", per_review_tokens=count_tokens(text), guarded_request_tokens=actual,
               actual_worker_request_tokens=observed[0], advertised_prompt_limit=6000,
               reservation=worker.GUARDED_RESERVATION_CEILING)

    def test_14_malformed_status_crashes_canonical_validator(self):
        with self.assertRaises(TypeError):
            contour.validate_output({"status": []}, "id", "critic")
        report("malformed_status", error="TypeError", classified_as_retryable=False)

    def test_15_score_only_edit_keeps_old_metadata(self):
        initial = rc._make_job()
        collect(page3())
        next_daily_job(initial)
        changed = replace(page3(), items=tuple(replace(i, score_label="1") for i in page3().items))
        collect(changed)
        latest = ReviewCollectionJob.objects.order_by("-id").first()
        scores = list(latest.observations.values_list("review__score_label", flat=True))
        self.assertEqual(scores, ["8"]*3)
        report("score_only_edit", source_score="1", persisted_scores=scores)

    def test_17_browse_stops_repeated_no_progress_pages_fixed(self):
        gateway = sel.FakeGateway(new_releases=[sel._identity(1)])
        clock = rc.FakeClock(NOW)
        run_tick(gateway, clock)
        calls = []
        class ProbeStop(Exception):
            pass
        def repeated_page(page_number):
            calls.append(page_number)
            if len(calls) == 6:
                raise ProbeStop("test stops an otherwise unbounded fetch loop")
            return BrowsePage(games=(sel._identity(1),), has_next_page=True), sel._evidence("browse_page")
        gateway.iter_browse = repeated_page
        clock.instant += timedelta(hours=1)
        result = run_tick(gateway, clock)
        self.assertEqual(calls, [1,2])
        self.assertEqual(result.run.error_code, "browse_repeated_page")
        report("browse_no_progress_FIXED", repeated_page_requests=2, terminated_by=result.run.error_code)

    def test_18_expired_summary_attempt_remains_open(self):
        summary_job(18)
        clock = rc.FakeClock(NOW)
        claimed = worker.claim_next_job(clock)
        with httpx.Client(transport=httpx.MockTransport(lambda r: None)) as client:
            with patch.object(groq_adapter, "generate_summary", side_effect=RuntimeError("crash")):
                with self.assertRaises(RuntimeError):
                    worker.process_job(client, clock, claimed, api_key="fake",
                                       base_url=groq_adapter.DEFAULT_BASE_URL)
        clock.instant += timedelta(minutes=6)
        reclaimed = worker.claim_next_job(clock)
        attempt = SummaryAttempt.objects.get()
        self.assertIsNone(attempt.outcome)
        self.assertIsNone(attempt.completed_at)
        self.assertEqual(reclaimed.pk, claimed.pk)
        report("abandoned_attempt", reclaimed=True, old_attempt_outcome=attempt.outcome,
               old_attempt_completed_at=attempt.completed_at)

class AdditionalProbes(TestCase):
    def test_19_stale_core_owner_changes_a_processed_candidate(self):
        from processing.runner import process_candidate
        from processing.lease import StaleRun
        from processing import selector
        clock = rc.FakeClock(NOW)
        old_run = sel._make_run(clock, NOW, 0)
        sel._acquire(old_run, clock)
        cycle = DailyCycle.objects.create(business_date=NOW.date(), phase="browse")
        game = Game.objects.create(source_game_id="g1", canonical_locator="/game/g1/", title="G1")
        stale_candidate = DailyCandidate.objects.create(cycle=cycle, game=game, source_order=1)
        clock.instant += timedelta(hours=1)
        gateway = sel.FakeGateway()
        run_tick(gateway, clock)
        self.assertEqual(DailyCandidate.objects.get(pk=stale_candidate.pk).state, "processed")
        with self.assertRaises(StaleRun):
            process_candidate(gateway, clock, old_run, stale_candidate)
        self.assertEqual(DailyCandidate.objects.get(pk=stale_candidate.pk).state, "processing")
        clock.instant += timedelta(hours=1)
        result = run_tick(gateway, clock)
        self.assertEqual(result.run.processed_count, 1)
        report("stale_core_write_NEW", before="processed", after_stale_call="processing",
               reprocessed_same_day=result.run.processed_count)

    def test_20_current_corpus_cache_hit_is_permanently_stale(self):
        job = summary_job(20)
        clock = rc.FakeClock(NOW)
        with httpx.Client(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json=response_for_request(request)))) as client:
            worker.process_job(client, clock, worker.claim_next_job(clock), api_key="fake",
                               base_url=groq_adapter.DEFAULT_BASE_URL)
        old = job.source_corpus
        reviews = [item.review for item in old.items.all()]
        # Valid contract: outside-sample source change produces a new corpus, same model input.
        newer = sw._make_corpus(job.game, "critic", reviews + [sw._make_review(reviews[0].game_platform, "critic", 99)])
        newer.model_input_fingerprint = old.model_input_fingerprint
        newer.save(update_fields=["model_input_fingerprint"])
        newer.items.filter(ordinal=4).delete()
        newer.selected_count = old.selected_count
        newer.save(update_fields=["selected_count"])
        ReviewCorpus.objects.filter(pk=old.pk).update(created_at=NOW)
        ReviewCorpus.objects.filter(pk=newer.pk).update(created_at=NOW + timedelta(seconds=1))
        cache_hit = worker.ensure_job(newer)
        self.assertEqual(cache_hit.pk, job.pk)
        self.assertEqual(cache_hit.state, "succeeded")
        view = get_summaries(job.game)[0]
        self.assertEqual((view.state, view.stale_reason), ("stale", "collection_in_progress"))
        self.assertIsNone(worker.claim_next_job(clock))
        report("current_cache_hit_NEW", cached_job="succeeded", state=view.state,
               reason=view.stale_reason, corrective_job_exists=False)

    def test_21_duplicates_bypass_minimum_input_guard(self):
        rc._make_job()
        base = rc._item(1)
        page = ReviewPageDTO(items=tuple(replace(base, source_review_id=str(n)) for n in range(3)),
                             reported_total=3, next_cursor=None)
        collect(page)
        corpus = ReviewCorpus.objects.get()
        self.assertEqual((corpus.unique_count, corpus.selected_count), (3,1))
        clock = rc.FakeClock(NOW)
        sent = []
        def reply(request):
            sent.append(json.loads(json.loads(request.content)["messages"][1]["content"])["reviews"])
            return httpx.Response(200, json=response_for_request(request))
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            result = worker.process_job(client, clock, worker.claim_next_job(clock), api_key="fake",
                                        base_url=groq_adapter.DEFAULT_BASE_URL)
        self.assertEqual(len(sent[0]), 1)
        self.assertEqual(result.state, "succeeded")
        report("minimum_review_guard_NEW", collected_records=3, distinct_input_records=1,
               provider_calls=len(sent), state=result.state)

    def test_22_bad_source_score_aborts_batch(self):
        from tests.test_catalog_ingest import _platform
        from django.db import IntegrityError
        from processing.models import ProcessingRun
        gateway = sel.FakeGateway(new_releases=[sel._identity(1), sel._identity(2)])
        real_fetch = gateway.fetch_game
        def fetch(url):
            dto, evidence = real_fetch(url)
            if dto.source_game_id == "g1":
                dto = replace(dto, platforms=(_platform(metascore=101),))
            return dto, evidence
        gateway.fetch_game = fetch
        with self.assertRaises(IntegrityError):
            run_tick(gateway, rc.FakeClock(NOW))
        run = ProcessingRun.objects.get()
        states = list(DailyCandidate.objects.order_by("source_order").values_list("state", flat=True))
        self.assertEqual((run.status, states), ("running", ["processing", "pending"]))
        # Verify this value can reach the DTO through the real parser, not just a loose fake.
        from metacritic.parser import _parse_platform
        dto = _parse_platform(["p1", "PC", "gp1", "pc", {"score": 5}, 101],
                              {"id": 0, "name": 1, "relatedGameId": 2, "slug": 3, "criticScoreSummary": 4})
        self.assertEqual(dto.metascore, 101)
        report("invalid_score_batch_NEW", accepted_parser_score=101, run_state=run.status,
               candidate_states=states, second_game_processed=False)

    def test_23_core_attempt_limit_is_not_enforced(self):
        gateway = sel.FakeGateway(new_releases=[sel._identity(1)], failing_games={"g1"})
        clock = rc.FakeClock(NOW)
        for _ in range(7):
            run_tick(gateway, clock)
            clock.instant += timedelta(hours=1)
        candidate = DailyCandidate.objects.get()
        self.assertEqual((candidate.attempt_count, candidate.state), (7, "retryable"))
        report("core_retry_limit_NEW", attempts=candidate.attempt_count, state=candidate.state,
               documented_limit=5)

    def test_24_saved_content_video_is_missing_from_card(self):
        game = Game.objects.create(source_game_id="video24", canonical_locator="/game/video24/",
                                   title="Video 24", video_content_url="https://example.invalid/trailer.mp4")
        response = self.client.get(f"/games/{game.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, game.video_content_url)
        self.assertNotContains(response, "Watch trailer")
        report("content_video_hidden_NEW", content_url_saved=True, embed_url=None,
               trailer_link_rendered=False, http_status=response.status_code)

class ConcurrentQuotaProbe(TransactionTestCase):
    def test_16_two_workers_admit_more_than_tpm(self):
        for n in (161, 162):
            summary_job(n)
        clock = rc.FakeClock(NOW)
        claimed = [worker.claim_next_job(clock), worker.claim_next_job(clock)]
        barrier = Barrier(2)
        real_has_capacity = quota.has_capacity
        def synchronized_admission(clock, reservation):
            result = real_has_capacity(clock, reservation)
            barrier.wait(timeout=10)
            return result
        def run(job_id):
            connections.close_all()
            try:
                job = SummaryJob.objects.get(pk=job_id)
                with httpx.Client(transport=httpx.MockTransport(lambda request:
                    httpx.Response(200, json=response_for_request(request)))) as client:
                    return worker.process_job(client, clock, job, api_key="fake",
                                     base_url=groq_adapter.DEFAULT_BASE_URL).state
            finally:
                connections.close_all()
        with patch.object(quota, "has_capacity", synchronized_admission), ThreadPoolExecutor(2) as pool:
            states = list(pool.map(run, [job.pk for job in claimed]))
        reserved = SummaryAttempt.objects.aggregate(total=Sum("reserved_total_tokens"))["total"]
        self.assertEqual(states, ["succeeded", "succeeded"])
        self.assertEqual(reserved, 13600)
        report("concurrent_quota", states=states, admitted_tokens=reserved, tpm_limit=quota.FREE_TPM)

if __name__ == "__main__":
    raise SystemExit(bool(DiscoverRunner(verbosity=2, interactive=False).run_tests(["__main__"])))
