"""YTP-01 feasibility probe: find the most popular let's play and its text.

Research tooling, not an application check. For each title it runs one
YouTube Data API search, reads statistics for the results, applies the
candidate let's-play filter (ASM-B01), then asks youtube-transcript-api and
yt-dlp what text and audio the chosen video offers. It prints one JSON report
and never prints the API key.

    python probe_youtube.py --env .env.app "Hades II" "Hollow Knight: Silksong"

Needs `yt-dlp` and `youtube-transcript-api` (versions are reported).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from importlib.metadata import version

API = "https://www.googleapis.com/youtube/v3"
SEARCH_UNITS = 100
VIDEOS_UNITS = 1
MIN_SECONDS = 10 * 60
QUERY = '"{title}" let\'s play'
EXCLUDE = re.compile(
    r"\b(trailer|teaser|review|обзор|reveal|announcement|soundtrack|ost|"
    r"shorts?|reaction|tier list|news|explained|analysis|guide|tips|"
    r"no commentary|without commentary|no talking|asmr)\b",
    re.IGNORECASE,
)
# A let's play needs the blogger's narration, not only game audio (ASM-B01).
MIN_WORDS_PER_MINUTE = 60
TRANSCRIPT_TRIES = 3
ROMAN = {
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}
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


def normalise(text: str) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return " ".join(ROMAN.get(word, word) for word in words)


def rejection(title: str, video: dict) -> str | None:
    snippet = video["snippet"]
    if normalise(title) not in normalise(snippet["title"]):
        return "title-mismatch"
    if EXCLUDE.search(snippet["title"]):
        return "excluded-word"
    if snippet.get("liveBroadcastContent") not in (None, "none"):
        return "live"
    if seconds(video["contentDetails"]["duration"]) < MIN_SECONDS:
        return "too-short"
    if "viewCount" not in video.get("statistics", {}):
        return "hidden-views"
    return None


def search(title: str, key: str, query: str) -> dict:
    found = api(
        "search",
        key,
        part="snippet",
        q=query.format(title=title),
        type="video",
        maxResults="25",
        order="relevance",
        safeSearch="none",
    )
    ids = [item["id"]["videoId"] for item in found.get("items", [])]
    videos = (
        api("videos", key, part="snippet,statistics,contentDetails", id=",".join(ids))["items"]
        if ids
        else []
    )
    candidates: list[dict] = []
    rejected: dict[str, int] = {}
    for video in videos:
        reason = rejection(title, video)
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        candidates.append(
            {
                "video_id": video["id"],
                "title": video["snippet"]["title"],
                "channel": video["snippet"]["channelTitle"],
                "views": int(video["statistics"]["viewCount"]),
                "seconds": seconds(video["contentDetails"]["duration"]),
                "language": video["snippet"].get("defaultAudioLanguage"),
                "captions_flag": video["contentDetails"].get("caption"),
            }
        )
    candidates.sort(key=lambda item: item["views"], reverse=True)
    return {
        "results": len(ids),
        "rejected": rejected,
        "accepted": len(candidates),
        "top": candidates[:TRANSCRIPT_TRIES],
        "units": SEARCH_UNITS + (VIDEOS_UNITS if ids else 0),
    }


def transcript(video_id: str) -> dict:
    from youtube_transcript_api import YouTubeTranscriptApi

    started = time.monotonic()
    try:
        api_client = YouTubeTranscriptApi()
        listing = api_client.list(video_id)
        tracks = [
            {"language": item.language_code, "generated": item.is_generated} for item in listing
        ]
        chosen = next(iter(listing))
        fetched = chosen.fetch()
        text = " ".join(snippet.text for snippet in fetched)
        spoken = [word for word in text.split() if not word.startswith("[")]
        covered = fetched[-1].start + fetched[-1].duration if fetched else 0
        return {
            "ok": True,
            "tracks": tracks,
            "used": {"language": chosen.language_code, "generated": chosen.is_generated},
            "words": len(spoken),
            "covered_seconds": round(covered),
            "words_per_minute": round(len(spoken) / (covered / 60), 1) if covered else 0,
            "sample": text[:160],
            "elapsed": round(time.monotonic() - started, 1),
        }
    except Exception as error:  # noqa: BLE001 - the probe records any failure class
        return {"ok": False, "error": type(error).__name__, "detail": str(error)[:300]}


def audio(video_id: str) -> dict:
    import yt_dlp

    options: dict = {"quiet": True, "no_warnings": True, "skip_download": True}
    if os.environ.get("YTDLP_JS_RUNTIME"):
        options["js_runtimes"] = {os.environ["YTDLP_JS_RUNTIME"]: {}}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        formats = [
            fmt
            for fmt in (info or {}).get("formats") or []
            if fmt.get("vcodec") == "none"
            and fmt.get("acodec") not in (None, "none")
            and fmt.get("url")
        ]
        if not formats:
            return {"ok": False, "error": "no-audio-format"}
        smallest = min(formats, key=lambda fmt: fmt.get("abr") or 1e9)
        # yt-dlp returns https media URLs only.
        request = urllib.request.Request(smallest["url"], headers={"Range": "bytes=0-262143"})  # noqa: S310
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            sample = len(response.read())
        return {
            "ok": True,
            "audio_formats": len(formats),
            "smallest": {"ext": smallest.get("ext"), "abr_kbps": smallest.get("abr")},
            "first_bytes": sample,
        }
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": type(error).__name__, "detail": str(error)[:300]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="")
    parser.add_argument("--query", default=QUERY)
    parser.add_argument("--skip-search", action="store_true", help="probe ids given as titles")
    parser.add_argument("titles", nargs="+")
    args = parser.parse_args()
    report = {
        "tools": {name: version(name) for name in ("yt-dlp", "youtube-transcript-api")},
        "query": args.query,
        "min_words_per_minute": MIN_WORDS_PER_MINUTE,
        "min_seconds": MIN_SECONDS,
        "games": [],
    }
    key = "" if args.skip_search else load_key(args.env)
    for title in args.titles:
        entry: dict = {"title": title, "tried": []}
        if args.skip_search:
            ids = [title]
        else:
            entry["search"] = search(title, key, args.query)
            ids = [item["video_id"] for item in entry["search"]["top"]]
        # Most popular first; a candidate without enough narration is skipped.
        for video_id in ids:
            text = transcript(video_id)
            entry["tried"].append({"video_id": video_id, "transcript": text})
            if text.get("ok") and text["words_per_minute"] >= MIN_WORDS_PER_MINUTE:
                entry["chosen"] = video_id
                entry["audio"] = audio(video_id)
                break
        report["games"].append(entry)
    report["api_units"] = sum(game.get("search", {}).get("units", 0) for game in report["games"])
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(report, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
