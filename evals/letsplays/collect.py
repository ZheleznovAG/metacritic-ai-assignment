"""Freeze the YTP-02 let's-play candidate pool from the YouTube Data API.

Research tooling, not an application check. Games come from a catalogue
snapshot (kept outside Git): a fixed hand-picked list of well-known titles
plus a seeded random draw from the rest. For each game the pool is the union
of two unfiltered searches, so the pool does not depend on the selection rule
under evaluation. Only public video metadata is written; the key is never
printed.

    python evals/letsplays/collect.py --snapshot snapshot.json --env .env.app \
        --write evals/letsplays/candidates.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3"
QUERIES = ('"{title}" let\'s play', '"{title}" gameplay')
PER_QUERY = 25
SEED = 20261003
RANDOM_GAMES = 12
# Well-known catalogue games not used while YTP-01 shaped the draft rules.
KNOWN = (
    "Elden Ring",
    "Resident Evil Requiem",
    "Silent Hill: Townfall",
    "Pokemon Pokopia",
    "Final Fantasy VII Remake Intergrade",
    "DOOM: The Dark Ages - Revelations",
    "Mina the Hollower",
    "Graveyard Keeper 2",
)
DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def load_key(env_file: str) -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key and env_file:
        with open(env_file, encoding="utf-8") as handle:
            for line in handle:
                name, _, value = line.strip().partition("=")
                if name == "YOUTUBE_API_KEY":
                    key = value.strip().strip('"').strip("'")
    if not key:
        sys.exit("YOUTUBE_API_KEY is not set")
    return key


def api(path: str, key: str, **params: str) -> dict:
    query = urllib.parse.urlencode({**params, "key": key})
    with urllib.request.urlopen(f"{API}/{path}?{query}", timeout=30) as response:  # noqa: S310
        return json.load(response)


def seconds(iso: str) -> int:
    match = DURATION.fullmatch(iso)
    if not match:
        return 0
    days, hours, minutes, secs = (int(part or 0) for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + secs


def draw(snapshot: list[dict]) -> list[dict]:
    by_title = {game["title"]: game for game in snapshot}
    missing = [title for title in KNOWN if title not in by_title]
    if missing:
        sys.exit(f"known titles missing from snapshot: {missing}")
    rest = sorted(
        (game for game in snapshot if game["title"] not in KNOWN),
        key=lambda game: game["source_game_id"],
    )
    drawn = random.Random(SEED).sample(rest, RANDOM_GAMES)  # noqa: S311 - reproducible draw
    games = [{"stratum": "known", **by_title[title]} for title in KNOWN]
    games += [{"stratum": "random", **game} for game in drawn]
    return [
        {key: game[key] for key in ("stratum", "source_game_id", "title", "genres")}
        for game in games
    ]


def pool(title: str, key: str) -> tuple[list[dict], int]:
    ranks: dict[str, dict[str, int]] = {}
    units = 0
    for query in QUERIES:
        found = api(
            "search",
            key,
            part="snippet",
            q=query.format(title=title),
            type="video",
            maxResults=str(PER_QUERY),
            order="relevance",
            safeSearch="none",
        )
        units += 100
        for rank, item in enumerate(found.get("items", []), start=1):
            ranks.setdefault(item["id"]["videoId"], {})[query] = rank
    videos: list[dict] = []
    ids = list(ranks)
    for start in range(0, len(ids), 50):
        chunk = ids[start : start + 50]
        reply = api("videos", key, part="snippet,statistics,contentDetails", id=",".join(chunk))
        units += 1
        for video in reply["items"]:
            stats = video.get("statistics", {})
            videos.append(
                {
                    "video_id": video["id"],
                    "title": video["snippet"]["title"],
                    "channel": video["snippet"]["channelTitle"],
                    "published": video["snippet"]["publishedAt"],
                    "language": video["snippet"].get("defaultAudioLanguage"),
                    "live": video["snippet"].get("liveBroadcastContent"),
                    "seconds": seconds(video["contentDetails"]["duration"]),
                    "views": int(stats["viewCount"]) if "viewCount" in stats else None,
                    "ranks": ranks[video["id"]],
                }
            )
    videos.sort(key=lambda item: (-(item["views"] or -1), item["video_id"]))
    return videos, units


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--env", default="")
    parser.add_argument("--write", required=True)
    args = parser.parse_args()
    raw = open(args.snapshot, "rb").read()
    games = draw(json.loads(raw))
    key = load_key(args.env)
    total = 0
    for game in games:
        game["candidates"], units = pool(game["title"], key)
        total += units
        print(f"{game['title']}: {len(game['candidates'])} candidates", file=sys.stderr)
    report = {
        "version": "1.0.0",
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "seed": SEED,
        "queries": QUERIES,
        "per_query": PER_QUERY,
        "api_units": total,
        "games": games,
    }
    with open(args.write, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=1)
        handle.write("\n")


if __name__ == "__main__":
    main()
