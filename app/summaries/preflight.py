"""R01: count the exact serialized messages and schema in provider token units."""

from dataclasses import dataclass
from typing import Any

from reviews.selection import count_tokens

from summaries import contour

PROMPT_LIMIT = 6000
FRAMING_GUARD = 64


class PreflightError(Exception):
    """Safe, classified local error; no provider request was admitted."""


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    payload: dict[str, Any]
    raw_tokens: int
    guarded_tokens: int
    reserved_tokens: int
    sha256: str


def measure(payload: dict[str, Any]) -> PreparedRequest:
    serialized = contour.canonical_json(
        {"messages": payload["messages"], "response_format": payload["response_format"]}
    )
    try:
        raw = count_tokens(serialized)
    except (ValueError, RuntimeError, OSError, AttributeError) as error:
        raise PreflightError("tokenizer_unavailable") from error
    guarded = raw + FRAMING_GUARD
    return PreparedRequest(
        payload=payload,
        raw_tokens=raw,
        guarded_tokens=guarded,
        reserved_tokens=guarded + contour.MAX_COMPLETION_TOKENS,
        sha256=contour.sha256_bytes(contour.canonical_json(payload).encode("utf-8")),
    )


def prepare(correlation_id: str, audience: str, reviews: list[dict[str, str]]) -> PreparedRequest:
    prepared = measure(contour.build_request_payload(correlation_id, audience, reviews))
    if prepared.guarded_tokens > PROMPT_LIMIT:
        raise PreflightError("prompt_budget_exceeded")
    return prepared
