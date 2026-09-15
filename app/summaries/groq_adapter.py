"""Production Groq Chat Completions adapter.

Reuses the exact HTTP mechanics `evals/reviews/run_groq_eval.py` already proved (base URL
allowlist, bounded retry on transient errors, safe usage/response-metadata extraction, sanitised
error bodies) as production code — reimplemented here, not imported from `evals/`, since that
directory is a frozen historical harness the shipped app must not depend on at runtime.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from summaries import contour

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
USER_AGENT = (
    "metacritic-ai-assignment-worker/1.0 (+https://github.com/ZheleznovAG/metacritic-ai-assignment)"
)
RATE_LIMIT_HEADER_NAMES = (
    "retry-after",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
)


class GroqConfigError(Exception):
    """Local configuration (base URL, model, credentials) is missing or unsafe."""


class GroqApiError(Exception):
    """A sanitized Groq API error with retry metadata; never carries the API key."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        retry_after: float | None = None,
        rate_limit_headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.rate_limit_headers = rate_limit_headers or {}


@dataclass(frozen=True, slots=True)
class GroqCallResult:
    output: dict[str, Any] | None
    structural_errors: list[str]
    normalizations: list[str]
    returned_model: str | None
    provider_system_fingerprint: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    rate_limit_headers: dict[str, str]
    latency_ms: int


def validate_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.groq.com"
        or parsed.path.rstrip("/") != "/openai/v1"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise GroqConfigError("GROQ_API_BASE_URL must be https://api.groq.com/openai/v1")
    return base_url.rstrip("/")


def _safe_api_error(body: bytes, api_key: str) -> str:
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


def _post(
    client: httpx.Client, url: str, api_key: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        # No explicit per-request `timeout` here: the caller's `httpx.Client` already carries
        # the operator-configured timeout (`GROQ_API_TIMEOUT_SECONDS`), and a request-level
        # value would silently override it.
        response = client.post(
            url,
            content=contour.canonical_json(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
    except httpx.HTTPError as error:
        raise GroqApiError(f"Groq API connection failed: {type(error).__name__}") from error
    headers = {
        name: response.headers[name] for name in RATE_LIMIT_HEADER_NAMES if name in response.headers
    }
    if response.status_code != httpx.codes.OK:
        retry_after = None
        raw_retry_after = response.headers.get("Retry-After")
        if raw_retry_after:
            try:
                retry_after = float(raw_retry_after)
                if not math.isfinite(retry_after) or retry_after < 0:
                    retry_after = None
                elif retry_after > 86400:
                    retry_after = 86400.0
            except ValueError:
                retry_after = None
        raise GroqApiError(
            f"Groq API HTTP {response.status_code}: {_safe_api_error(response.content, api_key)}",
            status=response.status_code,
            retry_after=retry_after,
            rate_limit_headers=headers,
        )
    try:
        document = response.json()
    except json.JSONDecodeError as error:
        raise GroqApiError("Groq API returned a non-JSON response") from error
    if not isinstance(document, dict):
        raise GroqApiError("Groq API returned an unexpected JSON value")
    return document, headers


def _extract_output_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
    raise GroqApiError("Groq response does not contain assistant message content")


def _safe_usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    return result


def generate_summary(
    client: httpx.Client,
    *,
    api_key: str,
    base_url: str,
    correlation_id: str,
    audience: str,
    reviews: list[dict[str, str]],
    payload: dict[str, Any] | None = None,
) -> GroqCallResult:
    """One real Groq call. Raises `GroqApiError` for transport/HTTP failures (the caller decides
    retryable vs. delayed_capacity vs. failed); returns a result with `structural_errors` set
    (never raises) for a schema-invalid response, since that outcome is `retryable`, not fatal."""
    payload = (
        payload
        if payload is not None
        else contour.build_request_payload(correlation_id, audience, reviews)
    )
    started = time.perf_counter()
    response, rate_headers = _post(
        client, f"{validate_base_url(base_url)}/chat/completions", api_key, payload
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    try:
        raw_output = json.loads(_extract_output_text(response))
    except (GroqApiError, json.JSONDecodeError) as error:
        return GroqCallResult(
            output=None,
            structural_errors=[f"unparseable model output: {error}"],
            normalizations=[],
            returned_model=response.get("model")
            if isinstance(response.get("model"), str)
            else None,
            provider_system_fingerprint=response.get("system_fingerprint")
            if isinstance(response.get("system_fingerprint"), str)
            else None,
            prompt_tokens=_safe_usage(response).get("prompt_tokens"),
            completion_tokens=_safe_usage(response).get("completion_tokens"),
            total_tokens=_safe_usage(response).get("total_tokens"),
            rate_limit_headers=rate_headers,
            latency_ms=latency_ms,
        )

    normalized, normalizations = contour.normalize_output(raw_output)
    structural_errors = contour.validate_output(
        normalized, correlation_id, audience, {review["id"] for review in reviews}
    )
    usage = _safe_usage(response)
    returned_model = response.get("model") if isinstance(response.get("model"), str) else None
    system_fingerprint = (
        response.get("system_fingerprint")
        if isinstance(response.get("system_fingerprint"), str)
        else None
    )
    return GroqCallResult(
        output=normalized if not structural_errors else None,
        structural_errors=structural_errors,
        normalizations=normalizations,
        returned_model=returned_model,
        provider_system_fingerprint=system_fingerprint,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
        rate_limit_headers=rate_headers,
        latency_ms=latency_ms,
    )
