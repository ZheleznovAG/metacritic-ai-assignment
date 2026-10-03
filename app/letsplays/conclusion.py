"""The `letsplay-conclusion` contour 2.1.0: prompt, schema, budget and local validation.

Pure: file I/O, request shaping and checks, no ORM or HTTP. The transcript is cut into numbered
segments (`[S1] ... [S2] ...`); every like and dislike cites one segment by id, and the card shows
that segment as the quote. The model never writes quote text, so it cannot invent one.

History (`evals/letsplays/conclusion_results.md`): in 1.0.0 the model copied quotes itself and
2 of 14 answers were cut off at the 600-token ceiling; in 1.1.0 (ceiling 1 200, quotes allowed
to skip words with "...") 5 of 14 answers still held a quote that was paraphrased or not in the
transcript at all. Citing a segment id is the same design the review summaries use (`R01`).
2.0.0 had no invented quote, but read interface text and character lines as opinions, counted
momentary reactions as dislikes and cited one segment twice; 2.1.0 adds prompt rules for those
classes and rejects a repeated segment locally.

Budgets (`evals/letsplays/metric.md`, revised for the separate model): at most 2 500 transcript
words, a request of at most `MAX_REQUEST_TOKENS` provider tokens including the completion. The
model is `openai/gpt-oss-120b`, whose Groq limits are counted separately from the review
summaries' `openai/gpt-oss-20b`, so conclusions never take quota from summaries.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache
from importlib.metadata import version
from pathlib import Path
from typing import Any

import tiktoken

CONTOUR_DIR = Path(__file__).resolve().parent / "contour"
PROMPT_PATH = CONTOUR_DIR / "prompt_2_1_0.md"
SCHEMA_PATH = CONTOUR_DIR / "output_schema_2_0_0.json"

PROVIDER = "groq"
API_KIND = "chat_completions"
REQUESTED_MODEL = "openai/gpt-oss-120b"
PROMPT_VERSION = "2.1.0"
VALIDATION_VERSION = "2.1.0"
SCHEMA_VERSION = "2.0.0"
SEGMENTER_VERSION = "1.0.0"
TOKENIZER_ID = "o200k_harmony"

MAX_TRANSCRIPT_WORDS = 2500
MAX_COMPLETION_TOKENS = 1200
MAX_REQUEST_TOKENS = 5000
FRAMING_GUARD = 64
# A segment is a sentence, merged up to MIN words and split above MAX, so a quote stays short.
SEGMENT_MIN_WORDS = 6
SEGMENT_MAX_WORDS = 25
GENERATION_PARAMS = {
    "temperature": 0,
    "seed": 7,
    "max_completion_tokens": MAX_COMPLETION_TOKENS,
    "reasoning_effort": "low",
    "include_reasoning": False,
}
OUTPUT_KEYS = {"case_id", "status", "verdict", "sponsored", "likes", "dislikes"}
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class BudgetError(Exception):
    """The request cannot be made within the token budget; nothing was sent."""


@dataclass(frozen=True, slots=True)
class Prepared:
    payload: dict[str, Any]
    segments: dict[str, str]  # exactly what was sent: id -> text
    prompt_tokens: int  # measured locally, framing guard included
    reserved_tokens: int  # prompt plus the completion ceiling
    sha256: str

    @property
    def words(self) -> int:
        return sum(len(text.split()) for text in self.segments.values())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@cache
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(TOKENIZER_ID)


def count_tokens(text: str) -> int:
    return len(_encoding().encode(text, disallowed_special=()))


def load_system_prompt() -> str:
    markdown = PROMPT_PATH.read_text(encoding="utf-8")
    match = re.search(r"```text\s*\n(.*?)\n```", markdown, re.DOTALL)
    if not match:
        raise RuntimeError("prompt contour does not contain a fenced text system prompt")
    return match.group(1).strip()


def api_schema() -> dict[str, Any]:
    """Groq's strict-schema subset: the keywords the summaries contour already proved."""
    unsupported = {"$schema", "$id", "minItems", "maxItems"}

    def convert(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items() if key not in unsupported}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    result: dict[str, Any] = convert(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    return result


def segment(words: list[str]) -> list[str]:
    """Sentences of `SEGMENT_MIN_WORDS`-`SEGMENT_MAX_WORDS` words; unpunctuated text in chunks."""
    sentences = [part.split() for part in SENTENCE_END.split(" ".join(words)) if part.strip()]
    segments: list[list[str]] = []
    current: list[str] = []
    for sentence in sentences:
        while len(sentence) > SEGMENT_MAX_WORDS:
            if current:
                segments.append(current)
                current = []
            segments.append(sentence[:SEGMENT_MAX_WORDS])
            sentence = sentence[SEGMENT_MAX_WORDS:]
        if current and len(current) + len(sentence) > SEGMENT_MAX_WORDS:
            segments.append(current)
            current = []
        current += sentence
        if len(current) >= SEGMENT_MIN_WORDS:
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return [" ".join(words) for words in segments]


def build_payload(case_id: str, game: str, segments: dict[str, str]) -> dict[str, Any]:
    transcript = "\n".join(f"[{key}] {text}" for key, text in segments.items())
    user = {"case_id": case_id, "game": game, "transcript": transcript}
    return {
        "model": REQUESTED_MODEL,
        "messages": [
            {"role": "system", "content": load_system_prompt()},
            {"role": "user", "content": canonical_json(user)},
        ],
        "reasoning_effort": GENERATION_PARAMS["reasoning_effort"],
        "include_reasoning": GENERATION_PARAMS["include_reasoning"],
        "temperature": GENERATION_PARAMS["temperature"],
        "seed": GENERATION_PARAMS["seed"],
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "letsplay_conclusion", "strict": True, "schema": api_schema()},
        },
    }


def _measure(payload: dict[str, Any]) -> int:
    serialized = canonical_json(
        {"messages": payload["messages"], "response_format": payload["response_format"]}
    )
    return count_tokens(serialized) + FRAMING_GUARD


def prepare(case_id: str, game: str, transcript: str) -> Prepared:
    """Segment the first `MAX_TRANSCRIPT_WORDS` words, dropping trailing segments to fit."""
    parts = segment(transcript.split()[:MAX_TRANSCRIPT_WORDS])
    while parts:
        segments = {f"S{index}": text for index, text in enumerate(parts, start=1)}
        payload = build_payload(case_id, game, segments)
        prompt = _measure(payload)
        if prompt + MAX_COMPLETION_TOKENS <= MAX_REQUEST_TOKENS:
            return Prepared(
                payload=payload,
                segments=segments,
                prompt_tokens=prompt,
                reserved_tokens=prompt + MAX_COMPLETION_TOKENS,
                sha256=sha256_bytes(canonical_json(payload).encode("utf-8")),
            )
        excess = prompt + MAX_COMPLETION_TOKENS - MAX_REQUEST_TOKENS
        # About 30 tokens per segment; drop at least one per round.
        parts = parts[: -max(1, excess // 30)]
    raise BudgetError("transcript_does_not_fit")


def contour_versions() -> dict[str, str]:
    return {
        "provider": PROVIDER,
        "api_kind": API_KIND,
        "requested_model": REQUESTED_MODEL,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256_bytes(PROMPT_PATH.read_bytes()),
        "schema_version": SCHEMA_VERSION,
        "schema_sha256": sha256_bytes(SCHEMA_PATH.read_bytes()),
        "segmenter_version": SEGMENTER_VERSION,
        "validation_version": VALIDATION_VERSION,
        "tokenizer_id": TOKENIZER_ID,
        "tokenizer_version": version("tiktoken"),
        "max_transcript_words": str(MAX_TRANSCRIPT_WORDS),
    }


def contour_fingerprint() -> str:
    """Changes with the model, prompt, schema, segmenter, caps or generation parameters."""
    payload = {**contour_versions(), "generation_params": GENERATION_PARAMS}
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def validate_output(output: Any, case_id: str, segment_ids: set[str]) -> list[str]:
    """Local canonical validation; an opinion must cite a segment that was sent."""
    if not isinstance(output, dict):
        return ["output must be a JSON object"]
    errors: list[str] = []
    if set(output) != OUTPUT_KEYS:
        errors.append("keys must be exactly " + ", ".join(sorted(OUTPUT_KEYS)))
    if output.get("case_id") != case_id:
        errors.append("case_id does not match the request")
    status = output.get("status")
    if status not in {"sufficient", "insufficient"}:
        errors.append("status is invalid")
    verdict = output.get("verdict")
    if not isinstance(verdict, str) or len(verdict) > 300:
        errors.append("verdict must be a string of at most 300 characters")
    if not isinstance(output.get("sponsored"), bool):
        errors.append("sponsored must be a boolean")
    opinions = 0
    cited: set[str] = set()
    for field in ("likes", "dislikes"):
        items = output.get(field)
        if not isinstance(items, list) or len(items) > 3:
            errors.append(f"{field} must be an array of at most three items")
            continue
        for index, item in enumerate(items):
            prefix = f"{field}[{index}]"
            if not isinstance(item, dict) or set(item) != {"point", "segment"}:
                errors.append(f"{prefix} must contain exactly point and segment")
                continue
            point = item.get("point")
            if not isinstance(point, str) or not 1 <= len(point.strip()) <= 160:
                errors.append(f"{prefix}.point must contain 1-160 characters")
            cite = item.get("segment")
            if cite not in segment_ids:
                errors.append(f"{prefix}.segment must name a segment of this transcript")
            elif cite in cited:
                errors.append(f"{prefix}.segment is already cited by another point")
            else:
                cited.add(cite)
            opinions += 1
    if status == "insufficient":
        if opinions or verdict or output.get("sponsored"):
            errors.append("insufficient requires an empty verdict, no opinions and no sponsor")
    elif status == "sufficient":
        if not opinions:
            errors.append("sufficient requires at least one like or dislike")
        if not isinstance(verdict, str) or not verdict.strip():
            errors.append("sufficient requires a verdict")
    return errors


def opinions(output: dict[str, Any], segments: dict[str, str]) -> list[dict[str, str]]:
    """Validated output as stored and shown: the cited segment is the quote."""
    return [
        {
            "polarity": polarity,
            "point": item["point"],
            "segment": item["segment"],
            "quote": segments[item["segment"]],
        }
        for polarity, field in (("like", "likes"), ("dislike", "dislikes"))
        for item in output[field]
    ]
