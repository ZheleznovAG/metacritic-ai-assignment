#!/usr/bin/env python3
"""Run the frozen SPK-05 review-summarization evaluation on Groq Free Plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "evals" / "reviews"
CASES_PATH = EVAL_DIR / "cases.json"
PROMPT_PATH = EVAL_DIR / "prompt.md"
SCHEMA_PATH = EVAL_DIR / "output.schema.json"
RUNS_DIR = ROOT / ".eval-runs" / "reviews"

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-20b"
RUNNER_VERSION = "1.1.0"
PROMPT_VERSION = "3.0.0"
OUTPUT_SCHEMA_VERSION = "2.1.0"
OUTPUT_NORMALIZER_VERSION = "1.0.0"
MAX_COMPLETION_TOKENS = 800
FREE_RPM = 30
FREE_RPD = 1000
FREE_TPM = 8000
FREE_TPD = 200000
INSUFFICIENT_REASON = "not_enough_meaningful_reviews"
OUTPUT_KEYS = {
    "case_id",
    "audience",
    "status",
    "likes",
    "dislikes",
    "insufficient_data_reason",
}


class ConfigError(RuntimeError):
    """Raised when local configuration is incomplete or unsafe."""


class ApiError(RuntimeError):
    """Raised for a sanitized Groq API error with retry metadata."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.attempts = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_dotenv(path: Path) -> dict[str, str]:
    """Read the small KEY=VALUE subset used by this spike without dependencies."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f".env line {number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ConfigError(f".env line {number} has an invalid key")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def setting(dotenv: dict[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key, dotenv.get(key, default)).strip()


def extract_system_prompt(markdown: str) -> str:
    match = re.search(r"```text\s*\n(.*?)\n```", markdown, re.DOTALL)
    if not match:
        raise ConfigError("prompt.md does not contain a fenced text system prompt")
    return match.group(1).strip()


def validate_static_inputs(cases_document: Any, schema: Any, system_prompt: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(cases_document, dict):
        return ["cases.json must be an object"]
    cases = cases_document.get("cases")
    if not isinstance(cases, list) or not cases:
        return ["cases.json must contain a non-empty cases array"]
    if not system_prompt:
        errors.append("system prompt must not be empty")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        errors.append("output schema must describe an object")
    elif set(schema.get("required", [])) != OUTPUT_KEYS:
        errors.append("output schema required fields do not match the local validator")

    seen_cases: set[str] = set()
    present_kinds: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif case_id in seen_cases:
            errors.append(f"duplicate case id: {case_id}")
        else:
            seen_cases.add(case_id)
        if case.get("audience") not in {"critic", "user"}:
            errors.append(f"{prefix}.audience must be critic or user")
        if isinstance(case.get("kind"), str):
            present_kinds.add(case["kind"])
        reviews = case.get("reviews")
        if not isinstance(reviews, list) or not reviews:
            errors.append(f"{prefix}.reviews must be a non-empty array")
            continue
        review_ids: set[str] = set()
        for review_index, review in enumerate(reviews):
            review_prefix = f"{prefix}.reviews[{review_index}]"
            if not isinstance(review, dict) or set(review) != {"id", "text"}:
                errors.append(f"{review_prefix} must contain exactly id and text")
                continue
            review_id = review.get("id")
            text = review.get("text")
            if not isinstance(review_id, str) or not review_id:
                errors.append(f"{review_prefix}.id must be a non-empty string")
            elif review_id in review_ids:
                errors.append(f"{prefix} has duplicate review id {review_id}")
            else:
                review_ids.add(review_id)
            if not isinstance(text, str) or not text.strip():
                errors.append(f"{review_prefix}.text must be non-empty")

        oracle = case.get("oracle")
        if not isinstance(oracle, dict):
            errors.append(f"{prefix}.oracle must be an object")
        elif oracle.get("expected_status") not in {"ok", "insufficient_data"}:
            errors.append(f"{prefix}.oracle.expected_status is invalid")
        elif (
            oracle.get("expected_status") == "insufficient_data"
            and oracle.get("expected_reason") != INSUFFICIENT_REASON
        ):
            errors.append(f"{prefix}.oracle.expected_reason is invalid")

    required_kinds = {"ordinary", "contradictory", "sparse", "long", "instruction_injection"}
    missing_kinds = sorted(required_kinds - present_kinds)
    if missing_kinds:
        errors.append("missing required eval kinds: " + ", ".join(missing_kinds))
    return errors


def select_cases(cases: list[dict[str, Any]], requested: list[str]) -> list[dict[str, Any]]:
    if not requested:
        return cases
    by_id = {case["id"]: case for case in cases}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise ConfigError("unknown case id(s): " + ", ".join(unknown))
    requested_set = set(requested)
    return [case for case in cases if case["id"] in requested_set]


def model_input(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["id"],
        "audience": case["audience"],
        "reviews": case["reviews"],
    }


def api_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert the contract to Groq's supported strict-schema subset."""
    unsupported = {"$schema", "$id", "uniqueItems", "minItems", "maxItems"}

    def convert(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items() if key not in unsupported}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return convert(schema)


def request_payload(
    model: str,
    system_prompt: str,
    schema: dict[str, Any],
    case: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": canonical_json(model_input(case))},
        ],
        "reasoning_effort": "low",
        "include_reasoning": False,
        "temperature": 0,
        "seed": 7,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "review_summary",
                "strict": True,
                "schema": api_schema(schema),
            },
        },
    }


def request_size(payload: dict[str, Any]) -> dict[str, int]:
    serialized = canonical_json(
        {"messages": payload["messages"], "response_format": payload["response_format"]}
    )
    return {
        "input_characters": len(serialized),
        "input_utf8_bytes": len(serialized.encode("utf-8")),
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }


def safe_api_error(body: bytes, api_key: str) -> str:
    text = body.decode("utf-8", errors="replace").replace(api_key, "[REDACTED]")
    try:
        document = json.loads(text)
        error = document.get("error", document) if isinstance(document, dict) else {}
        if isinstance(error, dict):
            safe = {
                key: error[key]
                for key in ("type", "code", "message")
                if key in error and isinstance(error[key], (str, int, float, bool))
            }
            if safe:
                return canonical_json(safe)[:1000]
    except json.JSONDecodeError:
        pass
    return "response body omitted"


def request_json(
    url: str,
    api_key: str,
    timeout_seconds: int,
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    data = None if payload is None else canonical_json(payload).encode("utf-8")
    method = "GET" if payload is None else "POST"
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "metacritic-ai-assignment-spk05/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            response_headers = response.headers
    except urllib.error.HTTPError as exc:
        body = exc.read()
        detail = safe_api_error(body, api_key)
        retry_after: float | None = None
        raw_retry_after = exc.headers.get("Retry-After")
        if raw_retry_after:
            try:
                retry_after = float(raw_retry_after)
            except ValueError:
                retry_after = None
        raise ApiError(
            f"Groq API HTTP {exc.code}: {detail}",
            status=exc.code,
            retry_after=retry_after,
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"Groq API connection failed: {exc.reason}") from exc
    except (TimeoutError, ConnectionError) as exc:
        raise ApiError(f"Groq API connection failed: {type(exc).__name__}") from exc
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError("Groq API returned a non-JSON response") from exc
    if not isinstance(document, dict):
        raise ApiError("Groq API returned an unexpected JSON value")
    safe_headers = {
        name: response_headers[name]
        for name in (
            "x-ratelimit-limit-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        )
        if response_headers.get(name) is not None
    }
    return document, safe_headers


def extract_output_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            message = choice.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
    raise RuntimeError("Groq response does not contain assistant message content")


def safe_usage(response: dict[str, Any]) -> dict[str, Any]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
    details = usage.get("completion_tokens_details")
    if isinstance(details, dict):
        reasoning_tokens = details.get("reasoning_tokens")
        if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool):
            result["reasoning_tokens"] = reasoning_tokens
    return result


def safe_response_metadata(response: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    fingerprint = response.get("system_fingerprint")
    if isinstance(fingerprint, str):
        metadata["system_fingerprint"] = fingerprint
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        finish_reason = choices[0].get("finish_reason")
        if isinstance(finish_reason, str):
            metadata["finish_reason"] = finish_reason
    time_info = response.get("time_info")
    if isinstance(time_info, dict):
        safe_time = {
            key: time_info[key]
            for key in ("queue_time", "prompt_time", "completion_time", "total_time")
            if isinstance(time_info.get(key), (int, float))
            and not isinstance(time_info.get(key), bool)
        }
        if safe_time:
            metadata["provider_time_seconds"] = safe_time
    return metadata


def normalize_output(output: Any) -> tuple[Any, list[str]]:
    """Apply bounded, deterministic repairs that do not invent or rewrite claims."""
    if not isinstance(output, dict):
        return output, []
    normalized = json.loads(canonical_json(output))
    changes: list[str] = []
    for field in ("likes", "dislikes"):
        items = normalized.get(field)
        if isinstance(items, list) and len(items) > 5:
            changes.append(f"{field} truncated from {len(items)} to 5 items")
            normalized[field] = items[:5]
    return normalized, changes


def validate_output(output: Any, case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(output, dict):
        return ["output must be a JSON object"]
    missing = sorted(OUTPUT_KEYS - set(output))
    extra = sorted(set(output) - OUTPUT_KEYS)
    if missing:
        errors.append("missing keys: " + ", ".join(missing))
    if extra:
        errors.append("unexpected keys: " + ", ".join(extra))
    if output.get("case_id") != case["id"]:
        errors.append("case_id does not match the input")
    if output.get("audience") != case["audience"]:
        errors.append("audience does not match the input")

    status = output.get("status")
    expected_status = case.get("oracle", {}).get("expected_status")
    if status not in {"ok", "insufficient_data"}:
        errors.append("status is invalid")
    elif status != expected_status:
        errors.append(f"status should be {expected_status} for this frozen case")

    valid_review_ids = {review["id"] for review in case["reviews"]}
    for field in ("likes", "dislikes"):
        items = output.get(field)
        if not isinstance(items, list):
            errors.append(f"{field} must be an array")
            continue
        if len(items) > 5:
            errors.append(f"{field} contains more than five items")
        for index, item in enumerate(items):
            prefix = f"{field}[{index}]"
            if not isinstance(item, dict) or set(item) != {"claim", "support"}:
                errors.append(f"{prefix} must contain exactly claim and support")
                continue
            claim = item.get("claim")
            if not isinstance(claim, str) or not 1 <= len(claim) <= 160:
                errors.append(f"{prefix}.claim must contain 1-160 characters")
            support = item.get("support")
            if not isinstance(support, list) or len(support) != 1:
                errors.append(f"{prefix}.support must contain exactly one review id")
            elif any(not isinstance(value, str) or value not in valid_review_ids for value in support):
                errors.append(f"{prefix}.support contains an unknown review id")
            elif len(support) != len(set(support)):
                errors.append(f"{prefix}.support contains duplicate review ids")

    if status == "insufficient_data":
        if output.get("likes") != [] or output.get("dislikes") != []:
            errors.append("insufficient_data requires empty likes and dislikes")
        if output.get("insufficient_data_reason") != INSUFFICIENT_REASON:
            errors.append(
                f'insufficient_data_reason must be "{INSUFFICIENT_REASON}"'
            )
    elif status == "ok":
        if output.get("insufficient_data_reason") is not None:
            errors.append("ok requires a null insufficient_data_reason")
    return errors


def atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def require_api_key(dotenv: dict[str, str]) -> str:
    key = setting(dotenv, "GROQ_API_KEY")
    if not key or key.lower() in {"changeme", "replace-me", "your-key-here"}:
        raise ConfigError("GROQ_API_KEY is missing from the environment or .env")
    return key


def validate_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("GROQ_API_BASE_URL contains an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.groq.com"
        or parsed.path.rstrip("/") != "/openai/v1"
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("GROQ_API_BASE_URL must be https://api.groq.com/openai/v1")
    return base_url.rstrip("/")


def timeout_setting(dotenv: dict[str, str]) -> int:
    raw = setting(dotenv, "GROQ_API_TIMEOUT_SECONDS", "180")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError("GROQ_API_TIMEOUT_SECONDS must be an integer") from exc
    if not 10 <= value <= 600:
        raise ConfigError("GROQ_API_TIMEOUT_SECONDS must be between 10 and 600")
    return value


def retry_setting(dotenv: dict[str, str]) -> int:
    raw = setting(dotenv, "SPK05_MAX_RETRIES", "3")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError("SPK05_MAX_RETRIES must be an integer") from exc
    if not 0 <= value <= 5:
        raise ConfigError("SPK05_MAX_RETRIES must be between 0 and 5")
    return value


def check_access(base_url: str, model: str, api_key: str, timeout_seconds: int) -> None:
    document, _ = request_json(f"{base_url}/models", api_key, timeout_seconds)
    data = document.get("data")
    if not isinstance(data, list):
        raise RuntimeError("Groq models response does not contain a data array")
    model_ids = {
        item.get("id") for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if model not in model_ids:
        raise RuntimeError(f"configured model {model!r} is not available to this API key")
    print(f"Access check passed: configured model {model} is available ({len(model_ids)} models listed).")


def request_with_retry(
    url: str,
    api_key: str,
    timeout_seconds: int,
    payload: dict[str, Any],
    max_retries: int,
) -> tuple[dict[str, Any], dict[str, str], int]:
    retries = 0
    while True:
        try:
            response, headers = request_json(url, api_key, timeout_seconds, payload)
            return response, headers, retries
        except ApiError as exc:
            retryable = exc.status in {429, 500, 502, 503, 504} or exc.status is None
            if not retryable or retries >= max_retries:
                exc.attempts = retries + 1
                raise
            delay = exc.retry_after if exc.retry_after is not None else float(2**retries)
            delay = min(60.0, max(1.0, delay))
            retries += 1
            print(f"Transient Groq API error; retry {retries}/{max_retries} in {delay:g}s.")
            time.sleep(delay)


def build_manifest(
    cases_document: dict[str, Any],
    selected: list[dict[str, Any]],
    model: str,
    base_url: str,
    prompt_bytes: bytes,
    schema_bytes: bytes,
    cases_bytes: bytes,
    request_sizes: list[dict[str, int]],
    max_retries: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "runner_version": RUNNER_VERSION,
        "status": "running",
        "started_at": utc_now(),
        "completed_at": None,
        "eval_set_version": cases_document.get("eval_set_version"),
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "output_normalizer_version": OUTPUT_NORMALIZER_VERSION,
        "selected_case_ids": [case["id"] for case in selected],
        "provider": "Groq",
        "account_plan_required": "Free Plan",
        "api": "OpenAI-compatible Chat Completions API",
        "api_base_url": base_url,
        "model_requested": model,
        "models_returned": [],
        "parameters": {
            "reasoning_effort": "low",
            "include_reasoning": False,
            "temperature": 0,
            "seed": 7,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "tools": [],
            "structured_output_strict": True,
            "max_retries_per_case": max_retries,
        },
        "free_plan_snapshot": {
            "as_of": "2026-09-07",
            "model": DEFAULT_MODEL,
            "requests_per_minute": FREE_RPM,
            "requests_per_day": FREE_RPD,
            "tokens_per_minute": FREE_TPM,
            "tokens_per_day": FREE_TPD,
            "paid_fallback_configured": False,
        },
        "request_sizes": request_sizes,
        "artifacts": {
            "cases_sha256": sha256_bytes(cases_bytes),
            "prompt_sha256": sha256_bytes(prompt_bytes),
            "output_schema_sha256": sha256_bytes(schema_bytes),
        },
        "results": [],
        "totals": {
            "attempted": 0,
            "api_attempts": 0,
            "successful": 0,
            "structural_passes": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


def run_eval(
    cases_document: dict[str, Any],
    selected: list[dict[str, Any]],
    schema: dict[str, Any],
    system_prompt: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout_seconds: int,
    max_retries: int,
    prompt_bytes: bytes,
    schema_bytes: bytes,
    cases_bytes: bytes,
) -> Path:
    payloads = [request_payload(model, system_prompt, schema, case) for case in selected]
    request_sizes = [request_size(payload) for payload in payloads]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_path = RUNS_DIR / run_id / "run.json"
    manifest = build_manifest(
        cases_document,
        selected,
        model,
        base_url,
        prompt_bytes,
        schema_bytes,
        cases_bytes,
        request_sizes,
        max_retries,
    )
    atomic_write_json(run_path, manifest)

    try:
        for case, payload in zip(selected, payloads):
            manifest["totals"]["attempted"] += 1
            started = time.perf_counter()
            try:
                response, rate_headers, retries = request_with_retry(
                    f"{base_url}/chat/completions",
                    api_key,
                    timeout_seconds,
                    payload,
                    max_retries,
                )
                manifest["totals"]["api_attempts"] += retries + 1
                latency_ms = round((time.perf_counter() - started) * 1000)
                text = extract_output_text(response)
                parsed_output, normalizations = normalize_output(json.loads(text))
                usage = safe_usage(response)
                structural_errors = validate_output(parsed_output, case)
                returned_model = response.get("model") if isinstance(response.get("model"), str) else None
                result = {
                    "case_id": case["id"],
                    "audience": case["audience"],
                    "kind": case["kind"],
                    "status": "success",
                    "latency_ms": latency_ms,
                    "model_returned": returned_model,
                    "response_metadata": safe_response_metadata(response),
                    "usage": usage,
                    "rate_limit_headers": rate_headers,
                    "output": parsed_output,
                    "normalizations": normalizations,
                    "structural_errors": structural_errors,
                }
                manifest["results"].append(result)
                manifest["totals"]["successful"] += 1
                if not structural_errors:
                    manifest["totals"]["structural_passes"] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = usage.get(key)
                    if isinstance(value, int):
                        manifest["totals"][key] += value
                if returned_model and returned_model not in manifest["models_returned"]:
                    manifest["models_returned"].append(returned_model)
                atomic_write_json(run_path, manifest)
                print(
                    f"{case['id']}: response received in {latency_ms} ms; "
                    f"{usage.get('total_tokens', 'unknown')} tokens"
                )
            except (ApiError, json.JSONDecodeError, RuntimeError) as exc:
                latency_ms = round((time.perf_counter() - started) * 1000)
                if isinstance(exc, ApiError):
                    manifest["totals"]["api_attempts"] += exc.attempts
                if not any(item.get("case_id") == case["id"] for item in manifest["results"]):
                    manifest["results"].append(
                        {
                            "case_id": case["id"],
                            "audience": case["audience"],
                            "kind": case["kind"],
                            "status": "error",
                            "latency_ms": latency_ms,
                            "error": str(exc),
                        }
                    )
                atomic_write_json(run_path, manifest)
                print(f"{case['id']}: isolated error recorded; continuing.", file=sys.stderr)
                if isinstance(exc, ApiError) and exc.status in {400, 401, 403, 404}:
                    raise
        manifest["status"] = "completed"
    except Exception:
        manifest["status"] = "failed"
        raise
    finally:
        manifest["completed_at"] = utc_now()
        atomic_write_json(run_path, manifest)
        print(f"Sanitized run artifact: {run_path.relative_to(ROOT)}")
    return run_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-access", action="store_true", help="list accessible models; no inference")
    mode.add_argument("--dry-run", action="store_true", help="validate inputs and request sizes")
    mode.add_argument("--run", action="store_true", help="perform the free-plan frozen evaluation")
    parser.add_argument("--case", action="append", default=[], help="run only this case id; repeatable")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        dotenv = load_dotenv(ROOT / ".env")
        base_url = validate_base_url(setting(dotenv, "GROQ_API_BASE_URL", DEFAULT_BASE_URL))
        model = setting(dotenv, "GROQ_API_MODEL", DEFAULT_MODEL)
        if not model:
            raise ConfigError("GROQ_API_MODEL must not be empty")
        if model != DEFAULT_MODEL:
            raise ConfigError(
                f"SPK-05 is frozen to {DEFAULT_MODEL}; update the documented baseline before changing it"
            )
        timeout_seconds = timeout_setting(dotenv)
        max_retries = retry_setting(dotenv)

        if args.check_access:
            check_access(base_url, model, require_api_key(dotenv), timeout_seconds)
            return 0

        cases_bytes = CASES_PATH.read_bytes()
        prompt_bytes = PROMPT_PATH.read_bytes()
        schema_bytes = SCHEMA_PATH.read_bytes()
        cases_document = json.loads(cases_bytes.decode("utf-8"))
        schema = json.loads(schema_bytes.decode("utf-8"))
        system_prompt = extract_system_prompt(prompt_bytes.decode("utf-8"))
        errors = validate_static_inputs(cases_document, schema, system_prompt)
        if errors:
            raise ConfigError("invalid eval inputs:\n- " + "\n- ".join(errors))
        selected = select_cases(cases_document["cases"], args.case)
        payloads = [request_payload(model, system_prompt, schema, case) for case in selected]

        if args.dry_run:
            sizes = [request_size(payload) for payload in payloads]
            largest = max(sizes, key=lambda item: item["input_utf8_bytes"])
            print(f"Dry run passed: {len(selected)} frozen case(s), model {model}.")
            print(
                "Largest serialized input: "
                f"{largest['input_characters']} characters / {largest['input_utf8_bytes']} UTF-8 bytes; "
                f"completion cap {MAX_COMPLETION_TOKENS} tokens."
            )
            print(
                f"Documented Free Plan limits: {FREE_RPM} RPM, {FREE_RPD} RPD, "
                f"{FREE_TPM} TPM, {FREE_TPD} TPD."
            )
            print("No API request was made.")
            return 0

        run_eval(
            cases_document,
            selected,
            schema,
            system_prompt,
            model,
            base_url,
            require_api_key(dotenv),
            timeout_seconds,
            max_retries,
            prompt_bytes,
            schema_bytes,
            cases_bytes,
        )
        return 0
    except (ConfigError, FileNotFoundError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
