"""Let's-play worker (YTP-03) on PostgreSQL with fake YouTube and Groq providers."""

from datetime import UTC, datetime, timedelta
from typing import Any

from catalog.models import Game, GamePlatform
from django.test import TestCase
from letsplays import budget, worker
from letsplays.groq import ChatResult
from letsplays.models import LetsPlay, LetsPlayConclusion, LetsPlayTranscript, ProviderCall
from letsplays.youtube import Found, Heard, VideoFacts, YouTubeError
from summaries.groq_adapter import GroqApiError

START = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
TALK = (
    "welcome back to Star Courier everyone, honestly I love how the ship handles out here "
    "but the menus are so clunky, I hate digging through three screens just to refuel "
) * 8


class FakeClock:
    def __init__(self) -> None:
        self.instant = START

    def now_utc(self) -> datetime:
        return self.instant

    def advance(self, **delta: float) -> None:
        self.instant += timedelta(**delta)


def found(video_id: str, views: int, title: str = "Star Courier part 1") -> Found:
    return Found(video_id, title, "Channel", "2026-09-01T00:00:00Z", "en", "none", 1800, views)


def good_output(case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "sufficient",
        "verdict": "The creator enjoys flying the ship but finds the menus clunky.",
        "sponsored": False,
        "likes": [{"point": "Ship handling", "segment": "S1"}],
        "dislikes": [{"point": "Clunky menus", "segment": "S2"}],
    }


class FakeProviders:
    def __init__(self) -> None:
        self.results: list[Found] = [found("lp1", 900)]
        self.speech: dict[str, Heard | None] = {"lp1": Heard("en", TALK, 120.0)}
        self.captions_error: YouTubeError | None = None
        self.whisper_error: Exception | None = None
        self.chat_output: Any = "good"
        self.chat_error: GroqApiError | None = None
        self.calls: list[str] = []

    def search(self, title: str) -> list[Found]:
        self.calls.append(f"search:{title}")
        return self.results

    def facts(self, video_id: str) -> VideoFacts:
        self.calls.append(f"facts:{video_id}")
        return VideoFacts(1800, "en", f"https://audio/{video_id}")

    def captions(self, video_id: str, language: str | None, seconds: int) -> Heard | None:
        self.calls.append(f"captions:{video_id}")
        if self.captions_error:
            raise self.captions_error
        return self.speech.get(video_id)

    def whisper(self, audio_url: str) -> tuple[Heard, dict[str, str]]:
        video_id = audio_url.rsplit("/", 1)[1]
        self.calls.append(f"whisper:{video_id}")
        if self.whisper_error:
            raise self.whisper_error
        heard = self.speech.get(video_id)
        if heard is None:
            raise YouTubeError("audio_refused", "HTTP 403")
        return heard, {"x-ratelimit-remaining-requests": "1999"}

    def chat(self, payload: dict[str, Any]) -> ChatResult:
        self.calls.append("chat")
        if self.chat_error:
            raise self.chat_error
        case_id = payload["messages"][1]["content"].split('"case_id":"')[1].split('"')[0]
        output = good_output(case_id) if self.chat_output == "good" else self.chat_output
        return ChatResult(output, "openai/gpt-oss-120b", 1500, 300, 1800, {}, 900)


def make_game(n: int, *, metascore: int | None = None, title: str = "Star Courier") -> Game:
    game = Game.objects.create(
        source_game_id=f"g{n}", canonical_locator=f"/game/g{n}/", title=title
    )
    if metascore is not None:
        GamePlatform.objects.create(
            game=game,
            source_platform_id="pc",
            source_game_platform_id=f"gp{n}",
            slug="pc",
            name="PC",
            metascore=metascore,
        )
    return game


def run(clock: FakeClock, providers: FakeProviders, steps: int) -> list[str | None]:
    return [worker.advance(clock, providers) for _ in range(steps)]


class HappyPathTests(TestCase):
    def test_search_listen_conclude_keeps_text_tied_to_the_video(self) -> None:
        game = make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        outcomes = run(clock, providers, 3)
        self.assertEqual(outcomes[-1], "done: lp1")
        job = LetsPlay.objects.get(game=game)
        self.assertEqual((job.state, job.video_id, job.views), ("done", "lp1", 900))
        self.assertEqual(job.checks[0]["decision"], "accepted")
        self.assertEqual(job.checks[0]["source"], "captions")
        transcript = LetsPlayTranscript.objects.get(letsplay=job)
        self.assertEqual(transcript.video_id, "lp1")
        self.assertEqual(transcript.text, TALK)
        result = LetsPlayConclusion.objects.get(letsplay=job)
        self.assertEqual(result.transcript, transcript)
        self.assertEqual([item["polarity"] for item in result.opinions], ["like", "dislike"])
        self.assertIn(result.opinions[0]["quote"], TALK)
        self.assertEqual(result.opinions[0]["segment"], "S1")
        self.assertEqual(job.refresh_at, START + worker.REFRESH_AFTER)
        kinds = list(ProviderCall.objects.order_by("id").values_list("kind", "units", "outcome"))
        self.assertEqual(kinds[0], ("youtube_api", 201, "ok"))
        self.assertEqual(kinds[1], ("video", 1, "ok"))
        self.assertEqual(kinds[2], ("captions", 1, "ok"))
        self.assertEqual(kinds[3][0::2], ("chat", "ok"))
        self.assertIsNone(worker.advance(clock, providers))

    def test_games_with_a_metascore_go_first(self) -> None:
        make_game(1)
        scored = make_game(2, metascore=80)
        clock, providers = FakeClock(), FakeProviders()
        worker.advance(clock, providers)
        self.assertEqual(LetsPlay.objects.get().game, scored)

    def test_a_finished_game_is_searched_again_after_thirty_days(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        run(clock, providers, 3)
        clock.advance(days=31)
        self.assertTrue(str(worker.advance(clock, providers)).startswith("listening"))
        self.assertEqual(providers.calls.count("search:Star Courier"), 2)


class NotFoundTests(TestCase):
    def test_no_eligible_candidate_is_not_found_without_listening(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        providers.results = [found("clip", 900, "Star Courier - Official Trailer")]
        self.assertEqual(worker.advance(clock, providers), "not_found: 1 found, 0 to hear")
        self.assertFalse(any(call.startswith("captions") for call in providers.calls))

    def test_three_rejected_listens_end_in_not_found(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        providers.results = [found(f"v{n}", 1000 - n) for n in range(5)]
        providers.speech = {f"v{n}": Heard("en", "[Music] [Music]", 300.0) for n in range(5)}
        outcomes = []
        for _ in range(4):
            outcomes.append(worker.advance(clock, providers))
            clock.advance(minutes=11)  # one video page per ten minutes
        job = LetsPlay.objects.get()
        self.assertEqual(job.state, "not_found")
        self.assertEqual([check["video_id"] for check in job.checks], ["v0", "v1", "v2"])
        self.assertEqual({check["decision"] for check in job.checks}, {"too_little_speech"})

    def test_unavailable_audio_counts_as_a_listen(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        providers.speech = {}
        run(clock, providers, 2)
        job = LetsPlay.objects.get()
        self.assertEqual(job.state, "not_found")
        self.assertEqual(job.checks[0]["decision"], "unavailable")


class CaptionAndAudioTests(TestCase):
    def test_blocked_captions_fall_back_to_whisper_and_pause_for_a_day(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        providers.captions_error = YouTubeError("captions_blocked")
        run(clock, providers, 2)
        job = LetsPlay.objects.get()
        self.assertEqual(job.checks[0]["source"], "whisper")
        refused = ProviderCall.objects.get(kind="captions")
        self.assertEqual((refused.outcome, refused.error_code), ("refused", "captions_blocked"))
        clock.advance(hours=1)
        self.assertIsNotNone(budget.blocked_until("captions", 1, clock.now_utc()))
        clock.advance(hours=24)
        self.assertIsNone(budget.blocked_until("captions", 1, clock.now_utc()))

    def test_whisper_refusal_defers_the_listen_until_retry_after(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        providers.speech = {"lp1": Heard("en", TALK, 300.0)}
        providers.captions_error = YouTubeError("captions_blocked")
        providers.whisper_error = GroqApiError(
            "429", status=429, retry_after=900, rate_limit_headers={"retry-after": "900"}
        )
        run(clock, providers, 2)
        job = LetsPlay.objects.get()
        self.assertEqual(
            (job.state, job.last_error, job.checks), ("listening", "whisper_refused", [])
        )
        self.assertEqual(job.available_at, START + timedelta(seconds=900))
        self.assertIsNone(worker.advance(clock, providers))

    def test_a_network_failure_retries_the_step_without_using_a_listen(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        run(clock, providers, 1)

        def offline(video_id: str) -> VideoFacts:
            raise YouTubeError("youtube_unreachable", "Failed to resolve 'www.youtube.com'")

        providers.facts = offline  # type: ignore[method-assign]
        self.assertEqual(worker.advance(clock, providers), "listening: youtube_unreachable")
        job = LetsPlay.objects.get()
        self.assertEqual((job.checks, job.attempt_count), ([], 1))
        self.assertEqual(job.available_at, START + worker.BACKOFF[0])

    def test_yt_dlp_errors_are_split_into_blocks_network_and_video_problems(self) -> None:
        from letsplays import youtube

        for message, expected in (
            ("Unable to download API page: Failed to resolve 'www.youtube.com'", "network"),
            ("HTTP Error 503: Service Unavailable", "network"),
            ("HTTP Error 429: Too Many Requests", "blocked"),
            ("Sign in to confirm you're not a bot", "blocked"),
            ("Video unavailable. This video is private", "video"),
            ("Sign in to confirm your age", "video"),
        ):
            found = (
                "blocked"
                if youtube.BLOCK_SIGNS.search(message)
                else "network"
                if youtube.NETWORK_SIGNS.search(message)
                else "video"
            )
            self.assertEqual(found, expected, message)

    def test_a_bot_check_pauses_every_video_page_without_using_a_listen(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        run(clock, providers, 1)

        def blocked(video_id: str) -> VideoFacts:
            raise YouTubeError("youtube_blocked", "Sign in to confirm you're not a bot")

        providers.facts = blocked  # type: ignore[method-assign]
        self.assertEqual(worker.advance(clock, providers), "listening: waiting (youtube_blocked)")
        job = LetsPlay.objects.get()
        self.assertEqual((job.checks, job.attempt_count), ([], 0))
        self.assertEqual(job.available_at, START + timedelta(hours=12))
        self.assertIsNone(worker.advance(clock, providers))

    def test_video_pages_are_read_at_most_once_per_ten_minutes(self) -> None:
        ProviderCall.objects.create(kind="video", units=1, started_at=START)
        self.assertEqual(
            budget.blocked_until("video", 1, START + timedelta(minutes=3)),
            START + timedelta(minutes=10),
        )

    def test_whisper_budget_is_counted_in_audio_seconds(self) -> None:
        for _ in range(18):
            ProviderCall.objects.create(kind="whisper", units=320, started_at=START)
        self.assertEqual(budget.blocked_until("whisper", 320, START), START + timedelta(hours=1))


class BudgetAndFailureTests(TestCase):
    def test_spent_youtube_units_stop_the_search_before_any_call(self) -> None:
        game = make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        LetsPlay.objects.create(game=game, policy_version="1.0.0")  # enrolled before it ran out
        ProviderCall.objects.create(kind="youtube_api", units=8900, started_at=START)
        self.assertEqual(worker.advance(clock, providers), "searching: waiting (youtube_quota)")
        self.assertEqual(providers.calls, [])
        job = LetsPlay.objects.get()
        self.assertEqual(job.available_at, START + timedelta(days=1))

    def test_youtube_quota_refusal_waits_a_day(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()

        def refuse(title: str) -> list[Found]:
            raise YouTubeError("youtube_quota_exceeded")

        providers.search = refuse  # type: ignore[method-assign]
        self.assertEqual(
            worker.advance(clock, providers), "searching: waiting (youtube_quota_exceeded)"
        )
        self.assertEqual(LetsPlay.objects.get().attempt_count, 0)

    def test_a_citation_outside_the_transcript_is_retried_then_fails(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        bad = good_output("x")
        bad["likes"] = [{"point": "Story", "segment": "S999"}]
        providers.chat_output = bad
        run(clock, providers, 2)
        for _ in range(worker.MAX_ATTEMPTS):
            clock.advance(hours=13)
            worker.advance(clock, providers)
        job = LetsPlay.objects.get()
        self.assertEqual((job.state, job.last_error), ("failed", "malformed_conclusion"))
        self.assertFalse(LetsPlayConclusion.objects.exists())
        self.assertEqual(job.refresh_at, clock.now_utc() + worker.REFRESH_AFTER)

    def test_chat_rate_limit_waits_without_counting_an_attempt(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        providers.chat_error = GroqApiError("429", status=429, retry_after=30)
        outcomes = run(clock, providers, 3)
        self.assertEqual(outcomes[2], "concluding: waiting (chat_refused)")
        self.assertEqual(LetsPlay.objects.get().attempt_count, 0)

    def test_insufficient_text_is_a_finished_conclusion(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        providers.chat_output = {
            "case_id": "",
            "status": "insufficient",
            "verdict": "",
            "sponsored": False,
            "likes": [],
            "dislikes": [],
        }

        def chat(payload: dict[str, Any]) -> ChatResult:
            case_id = payload["messages"][1]["content"].split('"case_id":"')[1].split('"')[0]
            return ChatResult(
                {**providers.chat_output, "case_id": case_id}, None, 900, 50, 950, {}, 400
            )

        providers.chat = chat  # type: ignore[method-assign]
        run(clock, providers, 3)
        self.assertEqual(LetsPlayConclusion.objects.get().status, "insufficient")
        self.assertEqual(LetsPlay.objects.get().state, "done")


class EnrolmentTests(TestCase):
    def test_no_new_game_is_enrolled_while_one_waits(self) -> None:
        make_game(1)
        make_game(2)
        clock, providers = FakeClock(), FakeProviders()
        providers.captions_error = YouTubeError("captions_blocked")
        providers.whisper_error = GroqApiError("429", status=429, retry_after=900)
        run(clock, providers, 2)  # the first game now waits for Whisper capacity
        self.assertEqual(LetsPlay.objects.get().last_error, "whisper_refused")
        for _ in range(5):
            self.assertIsNone(worker.advance(clock, providers))
        self.assertEqual(LetsPlay.objects.count(), 1)

    def test_nothing_is_enrolled_when_the_search_budget_is_spent(self) -> None:
        make_game(1)
        ProviderCall.objects.create(kind="youtube_api", units=8900, started_at=START)
        self.assertIsNone(worker.claim(FakeClock()))
        self.assertFalse(LetsPlay.objects.exists())

    def test_a_google_rate_limit_counts_as_a_spent_quota(self) -> None:
        import json

        import httpx
        from letsplays import youtube

        body = json.dumps(
            {
                "error": {
                    "code": 429,
                    "message": "Quota exceeded for quota metric 'Search Queries'",
                    "errors": [{"reason": "rateLimitExceeded"}],
                }
            }
        )
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(429, text=body))
        )
        with self.assertRaises(YouTubeError) as raised:
            youtube.search(client, "key", "Star Courier")
        self.assertEqual(raised.exception.code, "youtube_quota_exceeded")


class LeaseTests(TestCase):
    def test_a_claimed_job_is_not_claimed_again_until_its_lease_expires(self) -> None:
        make_game(1)
        clock = FakeClock()
        first = worker.claim(clock)
        assert first is not None
        self.assertIsNone(worker.claim(clock))
        clock.advance(minutes=11)
        again = worker.claim(clock)
        assert again is not None
        self.assertEqual(again.pk, first.pk)

    def test_a_step_whose_lease_was_taken_over_writes_nothing(self) -> None:
        make_game(1)
        clock, providers = FakeClock(), FakeProviders()
        job = worker.claim(clock)
        assert job is not None
        LetsPlay.objects.filter(pk=job.pk).update(available_at=START + timedelta(hours=5))
        self.assertEqual(worker._search(clock, providers, job), "searching: lease lost")
        self.assertEqual(LetsPlay.objects.get().shortlist, [])
