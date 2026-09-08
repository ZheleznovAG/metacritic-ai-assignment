#!/usr/bin/env python3
"""Verify the maximum multilingual review-summary request in provider token units."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import tiktoken

import run_groq_eval as runner


ROOT = Path(__file__).resolve().parents[2]
TOKENIZER_ID = "o200k_harmony"
TOKEN_POLICY_VERSION = "1.0.0-candidate"
MAX_REVIEWS = 10
MAX_REVIEW_TOKENS = 450
PROMPT_TOKEN_LIMIT = 6000
TOKEN_OVERHEAD_GUARD = 64
MAX_COMPLETION_TOKENS = runner.MAX_COMPLETION_TOKENS
REQUEST_TOKEN_RESERVATION_LIMIT = 6800
FREE_TPM = runner.FREE_TPM

SEEDS = (
    "Exploration is rewarding and the quests react to choices, but frame pacing becomes uneven in large fights.",
    "Исследовать мир интересно, решения меняют задания, но в больших боях заметно падает частота кадров.",
    "探索过程很有吸引力，任务会回应玩家的选择，但大型战斗中的帧率并不稳定。",
    "الاستكشاف ممتع والمهام تستجيب للقرارات، لكن أداء الإطارات يتراجع في المعارك الكبيرة.",
    "探索は楽しく選択が任務に反映されるが、大規模な戦闘ではフレームレートが不安定になる。",
    "La exploración resulta gratificante y las misiones reaccionan a las decisiones, aunque el rendimiento cae en combates grandes.",
    "Die Erkundung macht Spaß und Entscheidungen verändern Aufgaben, doch in großen Kämpfen schwankt die Bildrate.",
    "Досліджувати світ цікаво, вибір змінює завдання, але у великих боях частота кадрів нестабільна.",
    "Keşif keyifli ve görevler seçimlere tepki veriyor, ancak büyük çatışmalarda kare hızı düşüyor.",
    "🎮 The controls feel precise and the world invites discovery, but crowded scenes cause visible stutter. 🌍",
)


def canonical_request_input(payload: dict[str, Any]) -> str:
    return runner.canonical_json(
        {"messages": payload["messages"], "response_format": payload["response_format"]}
    )


def encode_untrusted(encoding: Any, text: str) -> list[int]:
    """Treat token-like substrings in untrusted reviews as text, never control tokens."""
    return encoding.encode(text, disallowed_special=())


def repeat_past_limit(seed: str, encoding: Any) -> str:
    text = seed
    while len(encode_untrusted(encoding, text)) <= MAX_REVIEW_TOKENS:
        text += " " + seed
    return text


def build_boundary_case(encoding: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reviews: list[dict[str, str]] = []
    measurements: list[dict[str, Any]] = []
    for index, seed in enumerate(SEEDS, 1):
        source_text = repeat_past_limit(seed, encoding)
        source_tokens = encode_untrusted(encoding, source_text)
        bounded_text = encoding.decode(source_tokens[:MAX_REVIEW_TOKENS])
        bounded_tokens = encode_untrusted(encoding, bounded_text)
        reviews.append({"id": f"R{index:02d}", "text": bounded_text})
        measurements.append(
            {
                "id": f"R{index:02d}",
                "source_tokens": len(source_tokens),
                "input_tokens": len(bounded_tokens),
                "was_truncated": len(source_tokens) > MAX_REVIEW_TOKENS,
            }
        )
    case = {
        "id": "production_max_multilingual",
        "kind": "boundary",
        "audience": "user",
        "reviews": reviews,
        "oracle": {"expected_status": "ok"},
    }
    return case, measurements


def local_check() -> tuple[dict[str, Any], dict[str, Any]]:
    encoding = tiktoken.get_encoding(TOKENIZER_ID)
    system_prompt = runner.extract_system_prompt(runner.PROMPT_PATH.read_text(encoding="utf-8"))
    schema = runner.load_json(runner.SCHEMA_PATH)
    case, review_measurements = build_boundary_case(encoding)
    payload = runner.request_payload(runner.DEFAULT_MODEL, system_prompt, schema, case)
    serialized = canonical_request_input(payload)
    raw_prompt_tokens = len(encode_untrusted(encoding, serialized))
    estimated_prompt_tokens = raw_prompt_tokens + TOKEN_OVERHEAD_GUARD
    reserved_request_tokens = estimated_prompt_tokens + MAX_COMPLETION_TOKENS

    errors: list[str] = []
    if len(case["reviews"]) != MAX_REVIEWS:
        errors.append("boundary case does not contain the configured maximum review count")
    if any(item["input_tokens"] != MAX_REVIEW_TOKENS for item in review_measurements):
        errors.append("a production-maximum review is not exactly at its token limit")
    if any(not item["was_truncated"] for item in review_measurements):
        errors.append("the boundary case did not exercise truncation for every review")
    if estimated_prompt_tokens > PROMPT_TOKEN_LIMIT:
        errors.append("estimated prompt exceeds the prompt token limit")
    if reserved_request_tokens > REQUEST_TOKEN_RESERVATION_LIMIT:
        errors.append("prompt plus completion reservation exceeds the request token limit")
    if REQUEST_TOKEN_RESERVATION_LIMIT > FREE_TPM:
        errors.append("request reservation exceeds the documented Free Plan TPM limit")
    if errors:
        raise RuntimeError("token-boundary check failed:\n- " + "\n- ".join(errors))

    evidence = {
        "schema_version": "1.0.0",
        "token_policy_version": TOKEN_POLICY_VERSION,
        "model": runner.DEFAULT_MODEL,
        "tokenizer": {
            "id": TOKENIZER_ID,
            "library": "tiktoken",
            "library_version": tiktoken.__version__,
        },
        "boundary_case": {
            "id": case["id"],
            "audience": case["audience"],
            "review_count": len(case["reviews"]),
            "per_review_token_limit": MAX_REVIEW_TOKENS,
            "reviews": review_measurements,
            "request_input_sha256": runner.sha256_bytes(serialized.encode("utf-8")),
        },
        "budget": {
            "raw_serialized_prompt_tokens": raw_prompt_tokens,
            "provider_overhead_guard_tokens": TOKEN_OVERHEAD_GUARD,
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "prompt_token_limit": PROMPT_TOKEN_LIMIT,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "reserved_request_tokens": reserved_request_tokens,
            "request_reservation_limit": REQUEST_TOKEN_RESERVATION_LIMIT,
            "documented_free_tpm": FREE_TPM,
            "headroom_to_free_tpm": FREE_TPM - reserved_request_tokens,
        },
        "local_result": "pass",
    }
    return evidence, payload


def live_check(evidence: dict[str, Any], payload: dict[str, Any]) -> None:
    dotenv = runner.load_dotenv(ROOT / ".env")
    base_url = runner.validate_base_url(
        runner.setting(dotenv, "GROQ_API_BASE_URL", runner.DEFAULT_BASE_URL)
    )
    model = runner.setting(dotenv, "GROQ_API_MODEL", runner.DEFAULT_MODEL)
    if model != runner.DEFAULT_MODEL:
        raise runner.ConfigError(f"boundary check is fixed to {runner.DEFAULT_MODEL}")
    timeout_seconds = runner.timeout_setting(dotenv)
    response, headers = runner.request_json(
        f"{base_url}/chat/completions",
        runner.require_api_key(dotenv),
        timeout_seconds,
        payload,
    )
    usage = runner.safe_usage(response)
    actual_prompt = usage.get("prompt_tokens")
    actual_total = usage.get("total_tokens")
    estimate = evidence["budget"]["estimated_prompt_tokens"]
    if not isinstance(actual_prompt, int) or not isinstance(actual_total, int):
        raise RuntimeError("Groq response did not contain integer prompt/total token usage")
    if actual_prompt > estimate:
        raise RuntimeError(
            f"provider prompt usage {actual_prompt} exceeds guarded estimate {estimate}"
        )
    if actual_total > REQUEST_TOKEN_RESERVATION_LIMIT:
        raise RuntimeError(
            f"provider total usage {actual_total} exceeds reservation {REQUEST_TOKEN_RESERVATION_LIMIT}"
        )
    returned_model = response.get("model")
    if returned_model != runner.DEFAULT_MODEL:
        raise RuntimeError(f"Groq returned unexpected model {returned_model!r}")
    evidence["live"] = {
        "checked_at_utc": runner.utc_now(),
        "result": "pass",
        "model_returned": returned_model,
        "usage": usage,
        "prompt_estimate_minus_actual": estimate - actual_prompt,
        "rate_limit_headers": headers,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also make one inference call after the local preflight; output never includes model text",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        evidence, payload = local_check()
        if args.live:
            live_check(evidence, payload)
        else:
            evidence["live"] = {"result": "not_run"}
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0
    except (runner.ApiError, runner.ConfigError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
