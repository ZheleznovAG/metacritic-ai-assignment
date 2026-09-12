"""Production Groq Chat Completions adapter.

Reuses the exact HTTP mechanics `evals/reviews/run_groq_eval.py` already proved (base URL
allowlist, bounded retry on transient errors, safe usage/response-metadata extraction, sanitised
error bodies) as production code — reimplemented here, not imported from `evals/`, since that
directory is a frozen historical harness the shipped app must not depend on at runtime.
"""

from __future__ import annotations

import json
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
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_RETRIES = 3
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
RATE_LIMIT_HEADER_NAMES = (
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

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


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
        response = client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
    except httpx.HTTPError as error:
        raise GroqApiError(f"Groq API connection failed: {type(error).__name__}") from error
    if response.status_code != httpx.codes.OK:
        retry_after = None
        raw_retry_after = response.headers.get("Retry-After")
        if raw_retry_after:
            try:
                retry_after = float(raw_retry_after)
            except ValueError:
                retry_after = None
        raise GroqApiError(
            f"Groq API HTTP {response.status_code}: {_safe_api_error(response.content, api_key)}",
            status=response.status_code,
            retry_after=retry_after,
        )
    try:
        document = response.json()
    except json.JSONDecodeError as error:
        raise GroqApiError("Groq API returned a non-JSON response") from error
    if not isinstance(document, dict):
        raise GroqApiError("Groq API returned an unexpected JSON value")
    headers = {
        name: response.headers[name] for name in RATE_LIMIT_HEADER_NAMES if name in response.headers
    }
    return document, headers


def _post_with_retry(
    client: httpx.Client,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    max_retries: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    retries = 0
    while True:
        try:
            return _post(client, url, api_key, payload)
        except GroqApiError as error:
            retryable = error.status in RETRYABLE_STATUSES or error.status is None
            if not retryable or retries >= max_retries:
                raise
            delay = error.retry_after if error.retry_after is not None else float(2**retries)
            delay = min(60.0, max(1.0, delay))
            retries += 1
            time.sleep(delay)


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
        if isinstance(value, int) and not isinstance(value, bool):
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
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> GroqCallResult:
    """One real Groq call. Raises `GroqApiError` for transport/HTTP failures (the caller decides
    retryable vs. delayed_capacity vs. failed); returns a result with `structural_errors` set
    (never raises) for a schema-invalid response, since that outcome is `retryable`, not fatal."""
    payload = contour.build_request_payload(correlation_id, audience, reviews)
    started = time.perf_counter()
    response, rate_headers = _post_with_retry(
        client, f"{base_url}/chat/completions", api_key, payload, max_retries
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
    structural_errors = contour.validate_output(normalized, correlation_id, audience)
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
