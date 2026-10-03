"""`letsplay-conclusion` contour 2.1.0 (YTP-03): segments, budget, schema subset, validation."""

from typing import Any
from unittest import mock

from django.test import SimpleTestCase
from letsplays import conclusion

TRANSCRIPT = (
    "okay welcome back to Star Courier everybody. Honestly, I love how the ship handles in the "
    "asteroid belt! The menus though are so clunky, I hate digging through three screens to refuel."
)
SEGMENTS = {"S1", "S2", "S3"}


def output(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "case_id": "LP-T1",
        "status": "sufficient",
        "verdict": "The creator enjoys the flying but is annoyed by the menus.",
        "sponsored": False,
        "likes": [{"point": "Ship handling feels great", "segment": "S2"}],
        "dislikes": [{"point": "Clunky refuelling menus", "segment": "S3"}],
    }
    value.update(overrides)
    return value


class SegmentTests(SimpleTestCase):
    def test_sentences_become_segments_and_join_back_losslessly(self) -> None:
        words = TRANSCRIPT.split()
        parts = conclusion.segment(words)
        self.assertEqual(len(parts), 3)
        self.assertTrue(parts[1].startswith("Honestly, I love"))
        self.assertEqual(" ".join(parts).split(), words)

    def test_unpunctuated_speech_is_chunked_and_short_sentences_are_merged(self) -> None:
        parts = conclusion.segment(("word " * 60).split())
        self.assertEqual([len(part.split()) for part in parts], [25, 25, 10])
        merged = conclusion.segment("Wow. Nice. Okay then. Let us go now please.".split())
        self.assertEqual(merged, ["Wow. Nice. Okay then. Let us go now please."])

    def test_no_segment_exceeds_the_maximum(self) -> None:
        text = ("Short one. " + "a b c d e f g h i j k l m n o p q r s t u v w. ") * 20
        lengths = [len(part.split()) for part in conclusion.segment(text.split())]
        self.assertLessEqual(max(lengths), conclusion.SEGMENT_MAX_WORDS)


class ValidateOutputTests(SimpleTestCase):
    def test_an_answer_citing_sent_segments_passes(self) -> None:
        self.assertEqual(conclusion.validate_output(output(), "LP-T1", SEGMENTS), [])

    def test_an_unknown_segment_is_rejected(self) -> None:
        bad = output(likes=[{"point": "Great story", "segment": "S9"}])
        self.assertIn(
            "likes[0].segment must name a segment of this transcript",
            conclusion.validate_output(bad, "LP-T1", SEGMENTS),
        )

    def test_one_segment_cannot_support_two_points(self) -> None:
        twice = output(dislikes=[{"point": "Clunky menus", "segment": "S2"}])
        self.assertIn(
            "dislikes[0].segment is already cited by another point",
            conclusion.validate_output(twice, "LP-T1", SEGMENTS),
        )

    def test_a_written_quote_instead_of_a_segment_is_rejected(self) -> None:
        bad = output(likes=[{"point": "x", "quote": "I love how the ship handles"}])
        self.assertTrue(conclusion.validate_output(bad, "LP-T1", SEGMENTS))

    def test_insufficient_must_be_empty(self) -> None:
        empty = output(status="insufficient", verdict="", likes=[], dislikes=[])
        self.assertEqual(conclusion.validate_output(empty, "LP-T1", SEGMENTS), [])
        self.assertTrue(
            conclusion.validate_output(output(status="insufficient"), "LP-T1", SEGMENTS)
        )
        sponsored = output(status="insufficient", verdict="", likes=[], dislikes=[], sponsored=True)
        self.assertTrue(conclusion.validate_output(sponsored, "LP-T1", SEGMENTS))

    def test_sufficient_needs_an_opinion_and_a_verdict(self) -> None:
        self.assertTrue(
            conclusion.validate_output(output(likes=[], dislikes=[]), "LP-T1", SEGMENTS)
        )
        self.assertTrue(conclusion.validate_output(output(verdict=" "), "LP-T1", SEGMENTS))

    def test_shape_and_identity_are_checked(self) -> None:
        self.assertTrue(conclusion.validate_output(output(), "LP-OTHER", SEGMENTS))
        self.assertTrue(conclusion.validate_output(output(extra=1), "LP-T1", SEGMENTS))
        four = [{"point": "p", "segment": "S2"}] * 4
        self.assertTrue(conclusion.validate_output(output(likes=four), "LP-T1", SEGMENTS))
        self.assertTrue(conclusion.validate_output(output(sponsored="no"), "LP-T1", SEGMENTS))
        self.assertEqual(
            conclusion.validate_output(["not", "an", "object"], "LP-T1", SEGMENTS),
            ["output must be a JSON object"],
        )

    def test_stored_opinions_quote_the_cited_segment_verbatim(self) -> None:
        prepared = conclusion.prepare("LP-T1", "Star Courier", TRANSCRIPT)
        stored = conclusion.opinions(output(), prepared.segments)
        self.assertEqual(stored[0]["polarity"], "like")
        self.assertEqual(stored[0]["quote"], prepared.segments["S2"])
        self.assertIn("I love how the ship handles", stored[0]["quote"])


class PrepareTests(SimpleTestCase):
    def test_short_transcript_is_sent_whole_as_numbered_lines(self) -> None:
        prepared = conclusion.prepare("LP-T1", "Star Courier", TRANSCRIPT)
        self.assertEqual(set(prepared.segments), SEGMENTS)
        self.assertIn("[S2] Honestly, I love", prepared.payload["messages"][1]["content"])
        self.assertLessEqual(prepared.reserved_tokens, conclusion.MAX_REQUEST_TOKENS)
        self.assertEqual(prepared.payload["model"], "openai/gpt-oss-120b")

    def test_long_transcript_keeps_the_start_within_the_word_cap_and_token_budget(self) -> None:
        long = " ".join(f"word{index} extraordinarily." for index in range(5000))
        prepared = conclusion.prepare("LP-T1", "Star Courier", long)
        self.assertLessEqual(prepared.words, conclusion.MAX_TRANSCRIPT_WORDS)
        self.assertLessEqual(prepared.reserved_tokens, conclusion.MAX_REQUEST_TOKENS)
        self.assertTrue(long.startswith(" ".join(prepared.segments.values())))

    def test_a_request_that_cannot_fit_is_refused(self) -> None:
        with (
            mock.patch.object(conclusion, "MAX_REQUEST_TOKENS", 100),
            self.assertRaises(conclusion.BudgetError),
        ):
            conclusion.prepare("LP-T1", "Star Courier", TRANSCRIPT)

    def test_api_schema_keeps_the_proven_subset(self) -> None:
        schema = conclusion.api_schema()
        self.assertNotIn("$schema", schema)
        self.assertNotIn("maxItems", schema["properties"]["likes"])
        self.assertEqual(set(schema["$defs"]["opinion"]["required"]), {"point", "segment"})

    def test_fingerprint_follows_the_generation_parameters(self) -> None:
        before = conclusion.contour_fingerprint()
        with mock.patch.dict(conclusion.GENERATION_PARAMS, {"temperature": 1}):
            self.assertNotEqual(conclusion.contour_fingerprint(), before)
        self.assertEqual(conclusion.contour_fingerprint(), before)
