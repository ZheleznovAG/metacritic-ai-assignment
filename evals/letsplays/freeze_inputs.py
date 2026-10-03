"""Freeze the YTP-02 conclusion eval inputs.

The transcripts are third-party text and stay in .artifacts/ytp02/. This
script writes them as one JSONL file there and records, in Git, which video,
source and SHA-256 each case uses, with its oracle. English text is required:
captions are taken only when their track is English, otherwise the Whisper
transcript of the original audio is used.

    python evals/letsplays/freeze_inputs.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
ARTIFACTS = HERE.parent.parent / ".artifacts" / "ytp02"
# Controls: no creator narration, so a conclusion must report insufficient text.
CONTROLS = {
    "QA7CELP3s2M": ("Rogue Racer", "silence: Whisper returns filler only"),
    "iKyXn73EDs8": ("DOOM: The Dark Ages - Revelations", "cutscene dialogue only"),
}
# Read in the transcript: the creator says the video or stream is sponsored. N84q1nzOuUw was
# missed when the set was frozen (1.0.0) and found by the 2.0.0 eval run; the transcript says
# "This video is sponsored by Graveyard Keeper 2" (correction 1.0.1, conclusion_results.md).
SPONSORED = {"YQnC7ky6d24", "N84q1nzOuUw"}


def english_texts() -> dict[str, tuple[str, str]]:
    texts: dict[str, tuple[str, str]] = {}
    for line in (ARTIFACTS / "captions.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("text") and (row.get("language") or "").startswith("en"):
            texts[row["video_id"]] = ("captions", row["text"])
    for line in (ARTIFACTS / "speech.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("text") and row.get("whisper_language") == "English":
            texts.setdefault(row["video_id"], ("whisper", row["text"]))
    return texts


def main() -> None:
    labels = json.loads((HERE / "labels.json").read_text(encoding="utf-8"))
    texts = english_texts()
    cases = [
        (game["title"], game["expected"], "sufficient", None)
        for game in labels["games"]
        if game["expected"]
    ]
    cases += [(title, video, "insufficient", why) for video, (title, why) in CONTROLS.items()]
    records, inputs = [], []
    for number, (title, video, status, why) in enumerate(cases, start=1):
        source, text = texts[video]
        case_id = f"LP-{number:02d}"
        inputs.append({"case_id": case_id, "video_id": video, "text": text})
        records.append(
            {
                "case_id": case_id,
                "game": title,
                "video_id": video,
                "source": source,
                "words": len(text.split()),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "expected_status": status,
                "sponsored": video in SPONSORED,
                "note": why,
            }
        )
    with (ARTIFACTS / "conclusion_inputs.jsonl").open("w", encoding="utf-8", newline="\n") as out:
        for item in inputs:
            out.write(json.dumps(item, ensure_ascii=False) + "\n")
    frozen = {
        "version": "1.0.1",
        "corrections": [
            "1.0.1: LP-08 sponsored false -> true; the transcript states the sponsorship"
        ],
        "inputs": ".artifacts/ytp02/conclusion_inputs.jsonl",
        "cases": records,
    }
    (HERE / "conclusion_cases.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
