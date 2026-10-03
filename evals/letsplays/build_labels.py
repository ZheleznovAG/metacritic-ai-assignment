"""Write the frozen YTP-02 labels from the hand-assigned table below.

The table is the labelling record: one row per candidate that can decide a
game's expected answer (every candidate ranked by views above the expected
let's play, the let's play itself, and for games without one every candidate
that could plausibly be one). Labels follow the definitions in metric.md and
were assigned before any selector was written. Evidence says what decided a
label: `metadata` (title, channel, duration, declared language), `captions`
(first 15 minutes of captions read from the service host) or `whisper` (about
5 minutes of the original audio track). Third-party text stays outside Git.

    python evals/letsplays/build_labels.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
LETSPLAY = "letsplay"
LABELS = {
    "letsplay",  # creator plays this game and narrates in English throughout
    "letsplay-other-language",  # same, narrated in another language
    "silent",  # gameplay without the creator's narration (cutscenes, music)
    "review",  # scripted review, preview, impressions essay, "before you buy"
    "guide",  # tips, walkthrough explanations, "things to do first"
    "trailer",  # publisher or press trailer, official gameplay showcase
    "short",  # YouTube Short or clip of about a minute
    "roundup",  # several games: release lists, news, recommendations
    "multi-game",  # one session covering several games
    "wrong-game",  # another game sharing words with the title
    "unconfirmed-game",  # narrated play, but the game could not be confirmed
}

# game title -> [(video_id, label, evidence)], ordered by views as in candidates.json.
# `metadata` also covers a publish date before the game's first trailer (Rogue Racer).
TABLE: dict[str, list[tuple[str, str, str]]] = {
    "Elden Ring": [
        ("E3Huy2cdih0", "trailer", "metadata"),
        ("JldMvQMO_5U", "trailer", "metadata"),
        ("GWomHd7hlFk", LETSPLAY, "captions"),
    ],
    "Resident Evil Requiem": [
        ("5CLYiAc8SHg", "short", "metadata"),
        ("dn5_p5jaJn0", LETSPLAY, "whisper"),
    ],
    "Silent Hill: Townfall": [
        ("5RE1GwL_XIQ", LETSPLAY, "captions"),
    ],
    "Pokemon Pokopia": [
        ("qaGrShDlH48", "letsplay-other-language", "captions"),
        ("bILGvd0lNiA", "short", "metadata"),
        ("0q7J6rp3lMs", "short", "metadata"),
        ("ekxWBkP6ULU", LETSPLAY, "captions"),
    ],
    "Final Fantasy VII Remake Intergrade": [
        ("s1CmEhz9-o4", "review", "metadata"),
        ("VW1ZJuoTHn4", "guide", "metadata"),
        ("AnDPvHCujmI", "silent", "metadata"),
        ("AXwl4-JacKU", "review", "metadata"),
        ("43Jt-GG1PFA", "silent", "metadata"),
        ("QQtW8Nashh0", "short", "metadata"),
        ("yhMpmF9csH4", "guide", "metadata"),
        ("az2zXT6o7KM", "silent", "metadata"),
        ("ZHRIwxJhSks", "short", "metadata"),
        ("i9vo2SZwhMY", LETSPLAY, "captions"),
    ],
    "DOOM: The Dark Ages - Revelations": [
        ("r14Qm8lxJr8", "short", "metadata"),
        ("iKyXn73EDs8", "silent", "whisper"),
        ("IUBg6kpuB-M", "letsplay-other-language", "metadata"),
        ("TZ6Sex25Fro", LETSPLAY, "whisper"),
    ],
    "Mina the Hollower": [
        ("XMWG4Nvb2Z0", "short", "metadata"),
        ("HsPQyKS8vG0", LETSPLAY, "captions"),
    ],
    "Graveyard Keeper 2": [
        ("N84q1nzOuUw", LETSPLAY, "captions"),
    ],
    "Rogue Racer": [
        ("NVHr_-5nzeE", "wrong-game", "captions"),
        ("wIVCCv9Gzfw", "wrong-game", "metadata"),
        ("yN8Z26N_qDE", "wrong-game", "captions"),
        ("9Kl5q2afAAQ", "wrong-game", "metadata"),
        ("a1c65Ab_Smo", "wrong-game", "metadata"),
        ("UBC59a-Nn4Q", "wrong-game", "metadata"),
        ("kVDNWor60ug", "wrong-game", "metadata"),
        ("qLRpnHY8mzo", "wrong-game", "metadata"),
        ("XrWqMzRYNkQ", "wrong-game", "metadata"),
        ("-ronWlLrmdU", "silent", "metadata"),
        ("QA7CELP3s2M", "silent", "whisper"),
        ("viSA7XZhaFA", "wrong-game", "metadata"),
        ("fIq6kGe94PM", "wrong-game", "metadata"),
        ("Nh3ph9qGac4", "multi-game", "captions"),
        ("0TMoAAhATGI", "wrong-game", "metadata"),
        ("nZhtL22UfjI", "wrong-game", "metadata"),
        ("k481uCOAuWc", "wrong-game", "whisper"),
        ("h3e-Z7OXqR0", "wrong-game", "whisper"),
    ],
    "SiN: Reloaded": [
        ("nv3PxdX3w2s", "review", "captions"),
        ("Tw5DMMTfk5o", "trailer", "metadata"),
        ("25bIqY6X740", "trailer", "metadata"),
        ("TDQOhOzgYj0", "trailer", "metadata"),
        ("IYOzXE2mbIU", "review", "metadata"),
        ("YQnC7ky6d24", LETSPLAY, "whisper"),
    ],
    "Taskbar Colony": [],
    "WilderDash": [
        ("hfcUpgSIAwQ", "letsplay-other-language", "metadata"),
        ("H7_MpPNLzh8", "letsplay-other-language", "metadata"),
        ("3AnXOOvxoeg", "wrong-game", "metadata"),
        ("lY7PYnBhSMM", "wrong-game", "metadata"),
        ("CyAt91PWFIg", "roundup", "metadata"),
        ("UlewJ3wip_s", "roundup", "metadata"),
        ("xPzCySLumCw", "short", "metadata"),
        ("MigshEcPhqo", "short", "metadata"),
        ("HtdXy9Px6ns", "short", "metadata"),
        ("3n3dmaWB34s", "roundup", "metadata"),
        ("IhQbWbvNm6Y", "trailer", "metadata"),
        ("7sPjU1peNBk", "roundup", "metadata"),
        ("EAHi7-atB2U", LETSPLAY, "captions"),
    ],
    "Sakura: The Eternal Night": [
        ("w1IVHqtm9mg", "roundup", "metadata"),
        ("IEfQX66JLFE", "short", "metadata"),
    ],
    "Murdercartel": [
        ("MShPvG87XBE", "short", "metadata"),
        ("JRHw-i02ldE", "roundup", "metadata"),
        ("BCJceZmVjvA", "trailer", "metadata"),
        ("qxC4zytzFlk", "short", "metadata"),
        ("oIki8AztSuY", "roundup", "metadata"),
    ],
    "SuperSharket": [],
    "Panic Files: Buried Sanity": [
        ("GvkHybmubjQ", "letsplay-other-language", "metadata"),
        ("60RMbymNSlM", "short", "metadata"),
        ("nKwVkyU6nx8", "short", "metadata"),
        ("D8M0hNSLlv8", "short", "metadata"),
        ("LVYLocMGnws", "short", "metadata"),
        ("qtYAjK4igt0", "short", "metadata"),
        ("fie9UO81UBE", "roundup", "metadata"),
        ("4wPvpOOaXOU", LETSPLAY, "captions"),
    ],
    "Clipped Reality": [
        ("a_E8OGLlwc8", "multi-game", "metadata"),
        ("sDjlKgabU2E", "short", "metadata"),
        ("a7t-L9-W5fc", "wrong-game", "metadata"),
        ("KOWwZql72u4", "wrong-game", "metadata"),
        ("yzaRM4q69nE", "roundup", "metadata"),
        ("C7y7KZp4oO4", "short", "metadata"),
        ("qguZahH8AwI", "unconfirmed-game", "whisper"),
        ("CF4QWt5Ed8k", "wrong-game", "metadata"),
    ],
    "Chronime Puzzle: Birds": [
        ("HnZSJzdrrLA", "wrong-game", "metadata"),
        ("08OToEH4bSQ", "wrong-game", "metadata"),
        ("MM5UH5vSzqM", "roundup", "metadata"),
        ("sskTc_tJtFI", "short", "metadata"),
    ],
    "Kamenkik and Friends": [
        ("6l4AU155vKw", "roundup", "metadata"),
    ],
    "Active Matter": [
        ("_bvkLBN8HyU", LETSPLAY, "whisper"),
    ],
}


def main() -> None:
    source = HERE / "candidates.json"
    pool = json.loads(source.read_text(encoding="utf-8"))
    games = []
    for game in pool["games"]:
        rows = TABLE[game["title"]]
        known = {item["video_id"]: item for item in game["candidates"]}
        for video_id, label, evidence in rows:
            assert video_id in known, (game["title"], video_id)
            assert label in LABELS, (video_id, label)
            assert evidence in {"metadata", "captions", "whisper"}, video_id
        expected = next((video for video, label, _ in rows if label == LETSPLAY), None)
        if expected:
            # Every candidate with more views than the expected video must be labelled.
            ahead = {
                item["video_id"]
                for item in game["candidates"]
                if (item["views"] or 0) > known[expected]["views"]
            }
            assert ahead <= {video for video, _, _ in rows}, (game["title"], ahead)
        games.append(
            {
                "title": game["title"],
                "stratum": game["stratum"],
                "expected": expected,
                "labels": [
                    {"video_id": video, "label": label, "evidence": evidence}
                    for video, label, evidence in rows
                ],
            }
        )
    labels = {
        "version": "1.0.0",
        "candidates_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "games": games,
    }
    target = HERE / "labels.json"
    target.write_text(
        json.dumps(labels, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
