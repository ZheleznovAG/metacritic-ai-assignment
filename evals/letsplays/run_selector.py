"""Run the production let's-play policy on the frozen YTP-02 pool and score it.

Speech comes from the saved listens in .artifacts/ytp02/ (Whisper on the original audio first,
then English-or-not captions read on the service host). A video the policy wants to hear that has
no saved listen is reported as missing; fetch it with check_speech.py and run again. The report
stores only decisions and rates, never transcript text.

    python evals/letsplays/run_selector.py [--write evals/letsplays/selector_report.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "app"))

from letsplays import selection  # noqa: E402

import score_selection  # noqa: E402

ARTIFACTS = ROOT / ".artifacts" / "ytp02"
CAPTION_WINDOW = 15 * 60


def saved_listens(durations: dict[str, int]) -> dict[str, selection.Speech | None]:
    """Video id -> its speech, or None when the listen itself failed (e.g. audio 403)."""
    listens: dict[str, selection.Speech | None] = {}
    for line in (ARTIFACTS / "captions.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("text") is not None:
            covered = min(CAPTION_WINDOW, durations[row["video_id"]])
            listens[row["video_id"]] = selection.Speech(row["language"], row["text"], covered)
    for line in (ARTIFACTS / "speech.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("text") is not None and row.get("seconds"):
            # The original audio track decides the language; it replaces an automatic dub.
            listens[row["video_id"]] = selection.Speech(
                row["whisper_language"], row["text"], float(row["seconds"])
            )
        elif "Forbidden" in str(row.get("error")) and row["video_id"] not in listens:
            listens[row["video_id"]] = None
    return listens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write")
    args = parser.parse_args()
    pool = score_selection.load("candidates.json")
    labels = score_selection.load("labels.json")
    durations = {
        item["video_id"]: item["seconds"] for game in pool["games"] for item in game["candidates"]
    }
    listens = saved_listens(durations)
    missing: list[str] = []
    choices: dict[str, str | None] = {}
    trace = []
    for game in pool["games"]:
        candidates = [
            selection.Candidate(
                video_id=item["video_id"],
                title=item["title"],
                channel=item["channel"],
                views=item["views"],
                seconds=item["seconds"],
                language=item["language"],
                live=item["live"],
            )
            for item in game["candidates"]
        ]

        def listen(candidate: selection.Candidate) -> selection.Speech | None:
            if candidate.video_id not in listens:
                missing.append(candidate.video_id)
                return None
            return listens[candidate.video_id]

        choice = selection.choose(game["title"], candidates, listen)
        choices[game["title"]] = choice.video_id
        trace.append(
            {
                "title": game["title"],
                "chosen": choice.video_id,
                "checks": [
                    {"video_id": c.video_id, "decision": c.decision, "wpm": c.words_per_minute}
                    for c in choice.checks
                ],
            }
        )
    if missing:
        print("missing listens:", " ".join(missing))
    result = score_selection.score(choices, labels, pool)
    print(
        f"letsplay-select {selection.POLICY_VERSION}: {result['accurate']}/{result['games']} "
        f"accurate, {result['false_positives']} false positives, "
        f"{len(result['violations'])} violations, passed={result['passed']}"
    )
    for row in result["rows"]:
        if not row["hit"]:
            print(f"  miss {row['title']}: expected {row['expected']}, chose {row['chosen']}")
    if args.write and not missing:
        listens_digest = hashlib.sha256(
            b"".join((ARTIFACTS / name).read_bytes() for name in ("captions.jsonl", "speech.jsonl"))
        ).hexdigest()
        report = {
            "policy_version": selection.POLICY_VERSION,
            "labels_version": labels["version"],
            "listens_sha256": listens_digest,
            "listens": sum(len(row["checks"]) for row in trace),
            "result": {key: result[key] for key in ("accurate", "games", "false_positives")}
            | {"violations": result["violations"], "passed": result["passed"]},
            "trace": trace,
        }
        Path(args.write).write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
