"""`letsplay-select` policy (YTP-03): pure decisions on invented candidates and speech."""

from django.test import SimpleTestCase
from letsplays import selection
from letsplays.selection import Candidate, Speech

NARRATION = (
    "hey everyone welcome back today we are playing Star Courier and honestly I love how the "
    "ship handles but the menus are a bit clunky so let us see what happens next "
) * 6


def candidate(video_id: str, title: str, views: int | None, **overrides: object) -> Candidate:
    values: dict[str, object] = {
        "video_id": video_id,
        "title": title,
        "channel": "Some Channel",
        "views": views,
        "seconds": 1800,
        "language": "en",
        "live": "none",
    }
    values.update(overrides)
    return Candidate(**values)  # type: ignore[arg-type]


def english(text: str = NARRATION, seconds: float = 120) -> Speech:
    return Speech("en", text, seconds)


class ShortlistTests(SimpleTestCase):
    def test_metadata_rules_out_clips_trailers_live_and_other_languages(self) -> None:
        kept = selection.shortlist(
            [
                candidate("short", "Star Courier part 1", 9_000, seconds=59),
                candidate("trailer", "Star Courier - Official Trailer", 8_000),
                candidate("live", "Star Courier live", 7_000, live="live"),
                candidate("german", "Star Courier Folge 1", 6_000, language="de"),
                candidate("silent", "Star Courier FULL GAME No Commentary", 5_000),
                candidate("roundup", "Daily Steam Drop - 120 New Releases", 4_500),
                candidate("hidden", "Star Courier part 2", None),
                candidate("unknown-language", "Star Courier part 3", 3_000, language=None),
                candidate("kept", "Star Courier part 4", 2_000),
            ]
        )
        self.assertEqual([item.video_id for item in kept], ["unknown-language", "kept"])

    def test_order_is_by_views_then_id(self) -> None:
        kept = selection.shortlist(
            [candidate("b", "x", 10), candidate("a", "x", 10), candidate("c", "x", 99)]
        )
        self.assertEqual([item.video_id for item in kept], ["c", "a", "b"])


class ChooseTests(SimpleTestCase):
    def test_most_viewed_narrated_english_video_about_the_game_wins(self) -> None:
        heard: list[str] = []

        def listen(item: Candidate) -> Speech:
            heard.append(item.video_id)
            return english()

        choice = selection.choose(
            "Star Courier",
            [
                candidate("low", "Star Courier ep 2", 100),
                candidate("top", "Star Courier ep 1", 900),
            ],
            listen,
        )
        self.assertEqual(choice.video_id, "top")
        self.assertEqual(heard, ["top"])
        self.assertEqual(choice.checks[0].decision, "accepted")

    def test_music_or_cutscenes_alone_are_too_little_speech(self) -> None:
        choice = selection.choose(
            "Star Courier",
            [candidate("silent", "Star Courier walkthrough", 900)],
            lambda item: english("[Music] you will never escape [Music] run", 300),
        )
        self.assertIsNone(choice.video_id)
        self.assertEqual(choice.checks[0].decision, "too_little_speech")

    def test_the_spoken_language_decides_not_the_title(self) -> None:
        choice = selection.choose(
            "Star Courier",
            [candidate("dub", "Star Courier part 1", 900, language=None)],
            lambda item: Speech("es", NARRATION, 120),
        )
        self.assertEqual(choice.checks[0].decision, "not_english")

    def test_a_title_naming_the_game_still_needs_the_speech_to_touch_the_name(self) -> None:
        other_game = "welcome to the backrooms everyone this level is so creepy look at that " * 9
        choice = selection.choose(
            "Clipped Reality",
            [candidate("meme", "Vtubers No Clipped Reality | Escape The Backrooms", 900)],
            lambda item: english(other_game),
        )
        self.assertEqual(choice.checks[0].decision, "other_game")

    def test_an_unnamed_title_is_accepted_when_the_speech_names_the_game(self) -> None:
        spoken = "okay so this is resident evil 9 requiem and I am already scared " * 10
        choice = selection.choose(
            "Resident Evil Requiem",
            [candidate("ep1", "WELCOME TO THE NEW ZOMBIE CITY | GAMEPLAY #1", 900)],
            lambda item: english(spoken),
        )
        self.assertEqual(choice.video_id, "ep1")

    def test_at_most_three_listens_per_game(self) -> None:
        heard: list[str] = []

        def listen(item: Candidate) -> Speech | None:
            heard.append(item.video_id)
            return None

        choice = selection.choose(
            "Star Courier",
            [candidate(str(views), "Star Courier part", views) for views in range(10, 15)],
            listen,
        )
        self.assertIsNone(choice.video_id)
        self.assertEqual(len(heard), selection.MAX_LISTENS)
        self.assertEqual({check.decision for check in choice.checks}, {"unavailable"})

    def test_same_input_gives_the_same_choice(self) -> None:
        pool = [candidate(str(views), "Star Courier part", views) for views in range(10, 15)]
        first = selection.choose("Star Courier", pool, lambda item: english())
        second = selection.choose("Star Courier", list(reversed(pool)), lambda item: english())
        self.assertEqual(first, second)


class NameMatchingTests(SimpleTestCase):
    def test_roman_numerals_and_filler_words(self) -> None:
        self.assertTrue(selection.title_names_game("Hades II", "Hades 2 is a frustrating 10/10"))
        self.assertTrue(
            selection.title_names_game(
                "DOOM: The Dark Ages - Revelations", "Doom: Dark Ages | Revelations"
            )
        )
        self.assertFalse(selection.title_names_game("Rogue Racer", "Driving Rogue is NFS"))

    def test_spoken_name_tolerates_two_inserted_words_only(self) -> None:
        self.assertTrue(
            selection.speech_names_game("Resident Evil Requiem", "resident evil 9 requiem")
        )
        self.assertFalse(
            selection.speech_names_game(
                "Resident Evil Requiem", "resident evil is great but this requiem"
            )
        )

    def test_a_compound_name_may_be_spoken_as_two_words(self) -> None:
        self.assertTrue(
            selection.speech_touches_name("WilderDash", "we are looking at wilder dash")
        )
        self.assertFalse(selection.speech_touches_name("Taskbar Colony", "subnautica mods today"))

    def test_rate_counts_only_spoken_words(self) -> None:
        self.assertEqual(Speech("en", "[Music] one two three [Applause]", 60).words_per_minute, 3)
        self.assertEqual(Speech("en", "anything", 0).words_per_minute, 0)

    def test_policy_module_has_no_framework_or_network_dependency(self) -> None:
        import ast
        from pathlib import Path

        tree = ast.parse(Path(selection.__file__).read_text(encoding="utf-8"))
        roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertEqual(roots & {"django", "httpx", "yt_dlp", "youtube_transcript_api"}, set())
