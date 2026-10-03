"""Run the production `letsplay-conclusion` contour on the 14 frozen YTP-02 cases.

Inputs are the transcripts in .artifacts/ytp02/conclusion_inputs.jsonl, checked against the
SHA-256 frozen in conclusion_cases.json before anything is sent. Full outputs (with quotes copied
from third-party transcripts) go to .artifacts/ytp02/conclusions_run_<version>.json; the published summary
keeps verdicts, points, validation results and provider usage, without quotes.

    python evals/letsplays/run_conclusions.py --env .env
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "app"))

from letsplays import conclusion, groq  # noqa: E402

ARTIFACTS = ROOT / ".artifacts" / "ytp02"
PAUSE_SECONDS = 60  # gpt-oss-120b free tier: 8 000 tokens per minute, up to 5 000 per call


def groq_key(env_file: str) -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key and env_file:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            name, _, value = line.strip().partition("=")
            if name == "GROQ_API_KEY":
                key = value.strip().strip('"').strip("'")
    if not key:
        sys.exit("GROQ_API_KEY is not set")
    return key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="")
    args = parser.parse_args()
    cases = json.loads((HERE / "conclusion_cases.json").read_text(encoding="utf-8"))["cases"]
    texts = {
        row["case_id"]: row["text"]
        for row in map(
            json.loads,
            (ARTIFACTS / "conclusion_inputs.jsonl").read_text(encoding="utf-8").splitlines(),
        )
    }
    for case in cases:
        digest = hashlib.sha256(texts[case["case_id"]].encode("utf-8")).hexdigest()
        if digest != case["text_sha256"]:
            sys.exit(f"{case['case_id']}: transcript does not match the frozen hash")
    key = groq_key(args.env)
    full, published = [], []
    with httpx.Client(timeout=180) as client:
        for number, case in enumerate(cases):
            if number:
                time.sleep(PAUSE_SECONDS)
            prepared = conclusion.prepare(case["case_id"], case["game"], texts[case["case_id"]])
            row: dict = {
                "case_id": case["case_id"],
                "game": case["game"],
                "expected_status": case["expected_status"],
                "sponsored_expected": case["sponsored"],
                "words_sent": prepared.words,
                "segments_sent": len(prepared.segments),
                "estimated_prompt_tokens": prepared.prompt_tokens,
            }
            try:
                result = groq.chat(
                    client,
                    api_key=key,
                    base_url="https://api.groq.com/openai/v1",
                    payload=prepared.payload,
                )
            except groq.GroqApiError as error:
                row["error"] = str(error)[:300]
                full.append(row)
                published.append(row)
                print(case["case_id"], "error", row["error"][:120])
                continue
            errors = conclusion.validate_output(
                result.output, case["case_id"], set(prepared.segments)
            )
            row.update(
                returned_model=result.returned_model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=result.latency_ms,
                validation_errors=errors,
            )
            output = result.output if isinstance(result.output, dict) else {}
            full.append(
                {
                    **row,
                    "output": result.output,
                    "opinions": [] if errors else conclusion.opinions(output, prepared.segments),
                }
            )
            published.append(
                {
                    **row,
                    "status": output.get("status"),
                    "sponsored": output.get("sponsored"),
                    "verdict": output.get("verdict"),
                    "likes": [
                        [item.get("point"), item.get("segment")] for item in output.get("likes", [])
                    ],
                    "dislikes": [
                        [item.get("point"), item.get("segment")]
                        for item in output.get("dislikes", [])
                    ],
                }
            )
            print(
                case["case_id"],
                output.get("status"),
                f"prompt={result.prompt_tokens} completion={result.completion_tokens}",
                f"errors={len(errors)}",
            )
    run = {
        "contour_fingerprint": conclusion.contour_fingerprint(),
        "contour_versions": conclusion.contour_versions(),
        "cases": published,
    }
    suffix = conclusion.PROMPT_VERSION.replace(".", "_")
    (ARTIFACTS / f"conclusions_run_{suffix}.json").write_text(
        json.dumps({**run, "cases": full}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (HERE / f"conclusion_run_{suffix}.json").write_text(
        json.dumps(run, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
