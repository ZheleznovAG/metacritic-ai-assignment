"""Freeze the release dates of the YTP-02 games (public facts the service already stores).

`Game.release_date` comes from the detail page's JSON-LD `datePublished`; the frozen catalogue
snapshot predates that field, so the same parser reads it here, once, through the service's own
gateway. The page is located by the game's slug; a page whose source id differs from the
snapshot's is recorded as a mismatch, not used.

    python evals/letsplays/release_dates.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "app"))

from metacritic.gateway import MetacriticGateway  # noqa: E402


def slug(title: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")


def main() -> None:
    pool = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))
    gateway = MetacriticGateway()
    dates = {}
    try:
        for game in pool["games"]:
            url = f"https://www.metacritic.com/game/{slug(game['title'])}/"
            dto, evidence = gateway.fetch_game(url)
            if dto is None:
                dates[game["title"]] = {"url": url, "error": evidence.outcome}
            elif dto.source_game_id != game["source_game_id"]:
                dates[game["title"]] = {"url": url, "error": "source_id_mismatch"}
            else:
                released = dto.release_date.isoformat() if dto.release_date else None
                dates[game["title"]] = {"url": url, "release_date": released}
            print(game["title"], dates[game["title"]])
    finally:
        gateway.close()
    (HERE / "release_dates.json").write_text(
        json.dumps(dates, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
