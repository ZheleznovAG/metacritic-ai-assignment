"""Let's-play block on the public card (YTP-03, AC-YT-05): every state, never invented text."""

from datetime import UTC, datetime

from catalog.models import Game
from django.test import TestCase
from django.urls import reverse
from letsplays.models import LetsPlay, LetsPlayConclusion, LetsPlayTranscript

AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def make_game() -> Game:
    return Game.objects.create(source_game_id="g1", canonical_locator="/game/g1/", title="Star")


def chosen(game: Game, state: str = "done", **extra: object) -> LetsPlay:
    return LetsPlay.objects.create(
        game=game,
        state=state,
        policy_version="1.0.0",
        searched_at=AT,
        video_id="abc123",
        video_title="Star - Part 1 <live>",
        channel="Creator",
        views=12345,
        seconds=3600,
        **extra,
    )


def conclude(job: LetsPlay, status: str = "sufficient", **extra: object) -> LetsPlayConclusion:
    transcript = LetsPlayTranscript.objects.create(
        letsplay=job,
        video_id=job.video_id or "",
        source="whisper",
        language="English",
        seconds_covered=320.0,
        text="I love the ship",
        text_sha256="0" * 64,
        created_at=AT,
    )
    values: dict[str, object] = {
        "letsplay": job,
        "transcript": transcript,
        "contour_fingerprint": "f" * 64,
        "contour_versions": {"requested_model": "openai/gpt-oss-120b"},
        "status": status,
        "verdict": "The creator enjoys it <b>a lot</b>." if status == "sufficient" else "",
        "opinions": [{"polarity": "like", "point": "Ship handling", "quote": "I love the ship"}]
        if status == "sufficient"
        else [],
        "returned_model": "openai/gpt-oss-120b",
        "generated_at": AT,
    }
    values.update(extra)
    return LetsPlayConclusion.objects.create(**values)


class LetsPlayCardTests(TestCase):
    def page(self, game: Game) -> str:
        response = self.client.get(reverse("game-detail", args=[game.id]))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_no_job_yet_is_pending(self) -> None:
        self.assertIn("The let&#x27;s-play search has not run yet.", self.page(make_game()))

    def test_a_conclusion_links_the_video_it_came_from(self) -> None:
        game = make_game()
        conclude(chosen(game))
        html = self.page(game)
        self.assertIn('href="https://www.youtube.com/watch?v=abc123"', html)
        self.assertIn("Star - Part 1 &lt;live&gt;", html)
        self.assertIn("12345 views on 2026-10-03", html)
        self.assertIn("The creator enjoys it &lt;b&gt;a lot&lt;/b&gt;.", html)
        self.assertIn("Ship handling", html)
        self.assertIn("I love the ship", html)
        self.assertIn("From speech recognition of the first 5 min", html)
        self.assertIn("No complaints in the part heard.", html)
        self.assertIn("it can mistake a reaction for an opinion", html)
        self.assertNotIn("sponsored", html)

    def test_sponsorship_is_stated(self) -> None:
        game = make_game()
        conclude(chosen(game), sponsored=True)
        self.assertIn("The creator says this video is sponsored.", self.page(game))

    def test_too_little_commentary_shows_no_opinions(self) -> None:
        game = make_game()
        conclude(chosen(game), status="insufficient")
        html = self.page(game)
        self.assertIn("too little of the creator", html)
        self.assertNotIn("<h4>Likes</h4>", html)

    def test_not_found_says_so_with_the_date(self) -> None:
        game = make_game()
        LetsPlay.objects.create(
            game=game, state="not_found", policy_version="1.0.0", searched_at=AT
        )
        html = self.page(game)
        self.assertIn("No English let&#x27;s play with the creator&#x27;s own commentary", html)
        self.assertIn("Checked on 2026-10-03.", html)

    def test_a_failed_conclusion_keeps_the_video_and_gives_the_reason(self) -> None:
        game = make_game()
        chosen(game, state="failed", last_error="malformed_conclusion")
        html = self.page(game)
        self.assertIn("watch?v=abc123", html)
        self.assertIn("did not match the video&#x27;s transcript", html)
        self.assertNotIn("<h4>Likes</h4>", html)

    def test_waiting_for_capacity_is_explained(self) -> None:
        game = make_game()
        chosen(game, state="concluding", last_error="chat_budget")
        self.assertIn("waiting for model capacity", self.page(game))

    def test_the_rest_of_the_card_does_not_depend_on_let_s_plays(self) -> None:
        game = make_game()
        html = self.page(game)
        self.assertIn("AI review summaries", html)
        self.assertIn("Similar games", html)
