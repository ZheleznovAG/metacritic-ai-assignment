"""Replay saved speech/provider outputs offline; emit hashes/counts, never transcript text."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "evals/letsplays"))

from letsplays import conclusion, selection
import run_selector
import score_selection


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main():
    inputs = ROOT / ".artifacts/ytp02"
    original = read("evals/letsplays/selector_report.json")
    speech_hash = hashlib.sha256(b"".join((inputs / name).read_bytes()
                                         for name in ["captions.jsonl", "speech.jsonl"])).hexdigest()
    assert speech_hash == original["listens_sha256"], "Saved speech changed"
    pool, labels = read("evals/letsplays/candidates.json"), read("evals/letsplays/labels.json")
    durations = {c["video_id"]: c["seconds"] for g in pool["games"] for c in g["candidates"]}
    listens = run_selector.saved_listens(durations)
    choices, repeats, trace = {}, {}, []
    for game in pool["games"]:
        candidates = [selection.Candidate(**{key: c[key] for key in
                       ["video_id", "title", "channel", "views", "seconds", "language", "live"]})
                      for c in game["candidates"]]

        def listen(candidate):
            assert candidate.video_id in listens, "Replay lacks a requested listen"
            return listens[candidate.video_id]

        choice = selection.choose(game["title"], candidates, listen)
        choices[game["title"]] = choice.video_id
        repeats[game["title"]] = selection.choose(game["title"], candidates, listen).video_id
        trace.append({"title": game["title"], "chosen": choice.video_id,
                      "checks": [{"video_id": c.video_id, "decision": c.decision,
                                  "wpm": c.words_per_minute} for c in choice.checks]})
    assert choices == repeats, "Selector replay is not deterministic"
    assert trace == original["trace"], "Policy replay differs from saved trace"
    scored = score_selection.score(choices, labels, pool)
    assert {key: scored[key] for key in original["result"]} == original["result"]

    cases = read("evals/letsplays/conclusion_cases.json")["cases"]
    texts = {row["case_id"]: row["text"] for row in map(json.loads,
             (inputs / "conclusion_inputs.jsonl").read_text(encoding="utf-8").splitlines())}
    raw = json.loads((inputs / "conclusions_run_2_1_0.json").read_text(encoding="utf-8"))
    published = read("evals/letsplays/conclusion_run_2_1_0.json")
    expected = {case["case_id"] for case in cases}
    outputs = {row["case_id"]: row for row in raw["cases"]}
    assert set(texts) == set(outputs) == expected
    assert len(raw["cases"]) == len(expected), "Duplicate saved output"
    assert conclusion.contour_fingerprint() == raw["contour_fingerprint"] == published["contour_fingerprint"]
    validity, reserved = [], []
    for case in cases:
        case_id = case["case_id"]
        assert hashlib.sha256(texts[case_id].encode("utf-8")).hexdigest() == case["text_sha256"]
        prepared = conclusion.prepare(case_id, case["game"], texts[case_id])
        row = outputs[case_id]
        assert prepared.words == row["words_sent"] and len(prepared.segments) == row["segments_sent"]
        errors = conclusion.validate_output(row["output"], case_id, set(prepared.segments))
        assert errors == row["validation_errors"] == []
        assert conclusion.opinions(row["output"], prepared.segments) == row["opinions"]
        validity.append(case_id)
        reserved.append(prepared.reserved_tokens)
    print(json.dumps({"saved_speech_sha256": speech_hash, "selector_result": original["result"],
                      "selector_trace_reproduced": True, "selector_deterministic": True,
                      "conclusion_cases": len(validity), "transcript_hashes_match": True,
                      "contour_fingerprint": raw["contour_fingerprint"],
                      "structurally_valid": len(validity), "saved_quotes_reproduced": True,
                      "maximum_reserved_request_tokens": max(reserved),
                      "request_token_cap": conclusion.MAX_REQUEST_TOKENS,
                      "provider_calls": 0,
                      "limits": "Original inputs and provider answers replayed; semantic grades unchanged, not independently reassessed."}, indent=2))


if __name__ == "__main__":
    main()
