"""Choose a game's most popular English let's play: policy `letsplay-select` 1.0.0.

Pure and deterministic: no ORM, HTTP or provider calls. The caller supplies the search candidates
(public metadata) and a `listen` callback that returns what is spoken at the start of a video;
this module decides which videos are worth listening to and which one to accept.

Frozen definitions, metric and acceptance bar: `evals/letsplays/metric.md` (YTP-02). A let's play
is a video where the creator plays this game and talks in English throughout. "Most popular" is the
largest public view count among such videos. The policy:

1. drops what metadata already rules out: live or upcoming broadcasts, videos shorter than
   `MIN_SECONDS` (Shorts, clips, trailers), titles with a non-let's-play word (`EXCLUDE`), and
   videos whose declared audio language is set and is not English;
2. walks the rest by views, most viewed first, listening to at most `MAX_LISTENS` of them;
3. accepts the first one whose speech is English at `MIN_WORDS_PER_MINUTE` or more, and that is
   about this game (`about_this_game`): its title contains every word of the game's name and the
   speech says at least one of them, or, when the title does not name it, the speech does.

Speech rate separates a narrated session from music and cutscene dialogue: in the frozen set
(`evals/letsplays/selector_report.json`) rejected silent videos ran at 7-43 words per minute and
accepted narration at 50-238; the slowest accepted one sits exactly on the threshold.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

POLICY_VERSION = "1.0.0"
MIN_SECONDS = 5 * 60
MIN_WORDS_PER_MINUTE = 50
MAX_LISTENS = 3

EXCLUDE = re.compile(
    r"\b(trailers?|teasers?|reviews?|previews?|reveal|announcement|official|soundtrack|ost|"
    r"shorts|reaction|tier list|news|explained|analysis|guides?|tips|tricks|"
    r"before you buy|things (?:the game|to do|you)|no commentary|without commentary|"
    r"no talking|asmr|livestream archive|new releases|steam drop|upcoming|wishlist|"
    r"top \d+|\d+ (?:new|free|best|upcoming) \w*\s*games)\b",
    re.IGNORECASE,
)
ROMAN = {
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}
# Words that carry no identity in a game's name; "the" in "DOOM: The Dark Ages" is optional.
FILLER = frozenset({"the", "a", "an", "of", "and"})
# Spoken names gain a word or two ("Resident Evil 9 Requiem" for "Resident Evil Requiem").
SPOKEN_GAP = 2


@dataclass(frozen=True, slots=True)
class Candidate:
    video_id: str
    title: str
    channel: str
    views: int | None
    seconds: int
    language: str | None  # YouTube's declared default audio language, often missing
    live: str | None  # "none" for an ordinary upload


@dataclass(frozen=True, slots=True)
class Speech:
    """What a listen returned: the transcript language, its words and the seconds it covers."""

    language: str | None
    text: str
    seconds: float

    @property
    def words_per_minute(self) -> float:
        spoken = [word for word in self.text.split() if not word.startswith("[")]
        return len(spoken) / (self.seconds / 60) if self.seconds > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Check:
    video_id: str
    decision: str  # accepted | not_english | too_little_speech | other_game | unavailable
    words_per_minute: float | None


@dataclass(frozen=True, slots=True)
class Choice:
    video_id: str | None
    checks: tuple[Check, ...]
    speech: Speech | None


Listen = Callable[[Candidate], Speech | None]


def words(text: str) -> list[str]:
    tokens = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return [ROMAN.get(token, token) for token in tokens]


def name_words(game_title: str) -> list[str]:
    return [token for token in words(game_title) if token not in FILLER]


def title_names_game(game_title: str, video_title: str) -> bool:
    return set(name_words(game_title)) <= set(words(video_title))


def speech_names_game(game_title: str, text: str) -> bool:
    """The name's words appear in order, each within `SPOKEN_GAP` extra words of the previous."""
    wanted = name_words(game_title)
    if not wanted:
        return False
    spoken = [token for token in words(text) if token not in FILLER]
    for start, token in enumerate(spoken):
        if token != wanted[0]:
            continue
        position, found = start, 1
        while found < len(wanted):
            window = spoken[position + 1 : position + 2 + SPOKEN_GAP]
            if wanted[found] not in window:
                break
            position += 1 + window.index(wanted[found])
            found += 1
        if found == len(wanted):
            return True
    return False


def speech_touches_name(game_title: str, text: str) -> bool:
    """At least one word of the name is spoken (a closed compound may be said as two words)."""
    spoken = words(text)
    heard = set(spoken) | {
        first + second for first, second in zip(spoken, spoken[1:], strict=False)
    }
    return any(token in heard for token in name_words(game_title) if not token.isdigit())


def about_this_game(game_title: str, video_title: str, text: str) -> bool:
    """The title names the game and the speech touches its name, or the speech names it fully.

    A title alone is not enough: "Vtubers No Clipped Reality | Escape The Backrooms" names
    "Clipped Reality" but is about another game, and its speech never mentions the name.
    """
    if title_names_game(game_title, video_title):
        return speech_touches_name(game_title, text)
    return speech_names_game(game_title, text)


def is_english(language: str | None) -> bool:
    return language is not None and language.lower().split("-")[0] in {"en", "english"}


def worth_listening(candidate: Candidate) -> bool:
    if candidate.views is None or candidate.live not in (None, "none"):
        return False
    if candidate.seconds < MIN_SECONDS or EXCLUDE.search(candidate.title):
        return False
    return candidate.language is None or is_english(candidate.language)


def shortlist(candidates: list[Candidate]) -> list[Candidate]:
    eligible = [candidate for candidate in candidates if worth_listening(candidate)]
    return sorted(eligible, key=lambda candidate: (-(candidate.views or 0), candidate.video_id))


def choose(game_title: str, candidates: list[Candidate], listen: Listen) -> Choice:
    checks: list[Check] = []
    for candidate in shortlist(candidates)[:MAX_LISTENS]:
        speech = listen(candidate)
        if speech is None:
            checks.append(Check(candidate.video_id, "unavailable", None))
            continue
        rate = round(speech.words_per_minute, 1)
        if not is_english(speech.language):
            decision = "not_english"
        elif rate < MIN_WORDS_PER_MINUTE:
            decision = "too_little_speech"
        elif not about_this_game(game_title, candidate.title, speech.text):
            decision = "other_game"
        else:
            checks.append(Check(candidate.video_id, "accepted", rate))
            return Choice(candidate.video_id, tuple(checks), speech)
        checks.append(Check(candidate.video_id, decision, rate))
    return Choice(None, tuple(checks), None)
