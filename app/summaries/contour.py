"""The frozen SPK-05 AI contour: provider, prompt, schema, normalizer, and allowlisted parameters.

`prompt_3_0_0.md`/`output_schema_2_1_0.json` are byte-identical copies of the already-frozen
`evals/reviews/prompt.md`/`output.schema.json` (SHA-256 pinned below, matching
`research/feasibility/ai-summary.md`'s published hashes) — copied, not cross-imported, so the
production image does not depend on the `evals/` tree at runtime. No Django dependency: this module
is pure file I/O plus request-shaping, reusable by both the real adapter and tests.
"""

from __future__ import annotations

import hashlib
import json
import re
from importlib.metadata import version
from pathlib import Path
from typing import Any

CONTOUR_DIR = Path(__file__).resolve().parent / "contour"
PROMPT_PATH = CONTOUR_DIR / "prompt_3_0_0.md"
SCHEMA_PATH = CONTOUR_DIR / "output_schema_2_1_0.json"

PROVIDER = "groq"
API_KIND = "chat_completions"
REQUESTED_MODEL = "openai/gpt-oss-20b"
PROMPT_VERSION = "3.0.0"
SCHEMA_VERSION = "2.1.0"
NORMALIZER_VERSION = "1.0.0"
ADAPTER_VERSION = "1.1.0"
SELECTION_POLICY_VERSION = "1.0.0-candidate"
TOKENIZER_ID = "o200k_harmony"

MAX_COMPLETION_TOKENS = 800
GENERATION_PARAMS = {
    "temperature": 0,
    "seed": 7,
    "max_completion_tokens": MAX_COMPLETION_TOKENS,
    "reasoning_effort": "low",
    "include_reasoning": False,
}

# Published in research/feasibility/ai-summary.md; a mismatch here means the copied contour
# artifact has drifted from the frozen SPK-05 baseline.
EXPECTED_PROMPT_SHA256 = "39ecea05844a743d2b4d9dda995401efa162650f9f295515a097c72c3ce1861f"
EXPECTED_SCHEMA_SHA256 = "29648d18fbdc06c1707050d5f3d173ae5a5d30f7af9ade1b693ff049404cfec0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_system_prompt() -> str:
    markdown = PROMPT_PATH.read_text(encoding="utf-8")
    match = re.search(r"```text\s*\n(.*?)\n```", markdown, re.DOTALL)
    if not match:
        raise RuntimeError("prompt contour does not contain a fenced text system prompt")
    return match.group(1).strip()


def load_schema() -> dict[str, Any]:
    result: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return result


def api_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Groq's strict-schema subset does not support these keywords."""
    unsupported = {"$schema", "$id", "uniqueItems", "minItems", "maxItems"}

    def convert(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items() if key not in unsupported}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    result: dict[str, Any] = convert(schema)
    return result


def build_request_payload(
    correlation_id: str, audience: str, reviews: list[dict[str, str]]
) -> dict[str, Any]:
    schema = load_schema()
    system_prompt = load_system_prompt()
    user_message = {"case_id": correlation_id, "audience": audience, "reviews": reviews}
    return {
        "model": REQUESTED_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": canonical_json(user_message)},
        ],
        "reasoning_effort": GENERATION_PARAMS["reasoning_effort"],
        "include_reasoning": GENERATION_PARAMS["include_reasoning"],
        "temperature": GENERATION_PARAMS["temperature"],
        "seed": GENERATION_PARAMS["seed"],
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "review_summary", "strict": True, "schema": api_schema(schema)},
        },
    }


def contour_versions() -> dict[str, str]:
    return {
        "provider": PROVIDER,
        "api_kind": API_KIND,
        "requested_model": REQUESTED_MODEL,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256_bytes(PROMPT_PATH.read_bytes()),
        "schema_version": SCHEMA_VERSION,
        "schema_sha256": sha256_bytes(SCHEMA_PATH.read_bytes()),
        "normalizer_version": NORMALIZER_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "tokenizer_id": TOKENIZER_ID,
        "tokenizer_version": version("tiktoken"),
    }


def contour_fingerprint() -> str:
    """Any change to the contour (provider/model/prompt/schema/selection/normalizer/params)
    changes this, which changes SummaryJob's cache key — a new job even for unchanged reviews."""
    payload = {**contour_versions(), "generation_params": GENERATION_PARAMS}
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def normalize_output(output: Any) -> tuple[Any, list[str]]:
    """Bounded, deterministic repairs that never invent or rewrite claim text."""
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


OUTPUT_KEYS = {"case_id", "audience", "status", "likes", "dislikes", "insufficient_data_reason"}


def validate_output(output: Any, correlation_id: str, audience: str) -> list[str]:
    """Local canonical validation mirroring the frozen schema; never trusts the provider alone."""
    errors: list[str] = []
    if not isinstance(output, dict):
        return ["output must be a JSON object"]
    missing = sorted(OUTPUT_KEYS - set(output))
    extra = sorted(set(output) - OUTPUT_KEYS)
    if missing:
        errors.append("missing keys: " + ", ".join(missing))
    if extra:
        errors.append("unexpected keys: " + ", ".join(extra))
    if output.get("case_id") != correlation_id:
        errors.append("case_id does not match the request")
    if output.get("audience") != audience:
        errors.append("audience does not match the request")

    status = output.get("status")
    if status not in {"ok", "insufficient_data"}:
        errors.append("status is invalid")

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
            if (
                not isinstance(support, list)
                or len(support) != 1
                or not isinstance(support[0], str)
            ):
                errors.append(f"{prefix}.support must contain exactly one review id")

    if status == "insufficient_data":
        if output.get("likes") != [] or output.get("dislikes") != []:
            errors.append("insufficient_data requires empty likes and dislikes")
        if output.get("insufficient_data_reason") != "not_enough_meaningful_reviews":
            errors.append("insufficient_data_reason must be not_enough_meaningful_reviews")
    elif status == "ok" and output.get("insufficient_data_reason") is not None:
        errors.append("ok requires a null insufficient_data_reason")
    return errors
