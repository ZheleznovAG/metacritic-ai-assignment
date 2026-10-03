"""Groq calls for let's plays: one chat completion for a conclusion, one Whisper transcription.

Same mechanics and safety as `summaries.groq_adapter` (fixed base URL, sanitised errors that never
carry the key, rate-limit headers kept for admission), reusing its public error and URL checks.
Every call is a single attempt: retries and back-off belong to the durable job, not to this module.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from summaries.groq_adapter import (
    RATE_LIMIT_HEADER_NAMES,
    USER_AGENT,
    GroqApiError,
    validate_base_url,
)

from letsplays import conclusion

WHISPER_MODEL = "whisper-large-v3-turbo"
# Groq reports audio limits in these headers when it sends them; kept with the attempt.
AUDIO_HEADER_NAMES = RATE_LIMIT_HEADER_NAMES + (
    "x-ratelimit-limit-audio-seconds",
    "x-ratelimit-remaining-audio-seconds",
    "x-ratelimit-reset-audio-seconds",
)


@dataclass(frozen=True, slots=True)
class ChatResult:
    output: Any  # parsed JSON, or None when the content was not JSON
    returned_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    headers: dict[str, str]
    latency_ms: int


@dataclass(frozen=True, slots=True)
class Transcription:
    text: str
    language: str | None
    seconds: float | None
    headers: dict[str, str]
    latency_ms: int


def _safe_error(body: bytes, api_key: str) -> str:
    text = body.decode("utf-8", errors="replace").replace(api_key, "[REDACTED]")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return "response body omitted"
    error = document.get("error", document) if isinstance(document, dict) else {}
    if not isinstance(error, dict):
        return "response body omitted"
    safe = {
        key: error[key]
        for key in ("type", "code", "message")
        if key in error and isinstance(error[key], str | int | float | bool)
    }
    return json.dumps(safe, ensure_ascii=False)[:1000] if safe else "response body omitted"


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return min(value, 86400.0) if math.isfinite(value) and value >= 0 else None


def _checked(response: httpx.Response, api_key: str, names: tuple[str, ...]) -> dict[str, str]:
    headers = {name: response.headers[name] for name in names if name in response.headers}
    if response.status_code != httpx.codes.OK:
        raise GroqApiError(
            f"Groq API HTTP {response.status_code}: {_safe_error(response.content, api_key)}",
            status=response.status_code,
            retry_after=_retry_after(response),
            rate_limit_headers=headers,
        )
    return headers


def _usage(document: dict[str, Any], key: str) -> int | None:
    usage = document.get("usage")
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def chat(
    client: httpx.Client, *, api_key: str, base_url: str, payload: dict[str, Any]
) -> ChatResult:
    started = time.perf_counter()
    try:
        response = client.post(
            f"{validate_base_url(base_url)}/chat/completions",
            content=conclusion.canonical_json(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
    except httpx.HTTPError as error:
        raise GroqApiError(f"Groq API connection failed: {type(error).__name__}") from error
    headers = _checked(response, api_key, RATE_LIMIT_HEADER_NAMES)
    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        document = response.json()
    except json.JSONDecodeError as error:
        raise GroqApiError("Groq API returned a non-JSON response") from error
    if not isinstance(document, dict):
        raise GroqApiError("Groq API returned an unexpected JSON value")
    output: Any = None
    choices = document.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            try:
                output = json.loads(content)
            except json.JSONDecodeError:
                output = None
    model = document.get("model")
    return ChatResult(
        output=output,
        returned_model=model if isinstance(model, str) else None,
        prompt_tokens=_usage(document, "prompt_tokens"),
        completion_tokens=_usage(document, "completion_tokens"),
        total_tokens=_usage(document, "total_tokens"),
        headers=headers,
        latency_ms=latency_ms,
    )


def transcribe(client: httpx.Client, *, api_key: str, base_url: str, audio: Path) -> Transcription:
    started = time.perf_counter()
    try:
        with audio.open("rb") as handle:
            response = client.post(
                f"{validate_base_url(base_url)}/audio/transcriptions",
                data={"model": WHISPER_MODEL, "response_format": "verbose_json"},
                files={"file": (audio.name, handle, "audio/mp4")},
                headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT},
            )
    except httpx.HTTPError as error:
        raise GroqApiError(f"Groq API connection failed: {type(error).__name__}") from error
    headers = _checked(response, api_key, AUDIO_HEADER_NAMES)
    try:
        document = response.json()
    except json.JSONDecodeError as error:
        raise GroqApiError("Groq API returned a non-JSON response") from error
    if not isinstance(document, dict) or not isinstance(document.get("text"), str):
        raise GroqApiError("Groq transcription has no text")
    seconds = document.get("duration")
    language = document.get("language")
    return Transcription(
        text=document["text"].strip(),
        language=language if isinstance(language, str) else None,
        seconds=float(seconds) if isinstance(seconds, int | float) else None,
        headers=headers,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
