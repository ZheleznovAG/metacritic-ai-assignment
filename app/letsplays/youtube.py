"""YouTube access for let's plays: search, video facts, captions and an audio fragment.

Search and view counts use the official Data API with the owner's key. Captions and audio use
the unofficial `youtube-transcript-api` and `yt-dlp`, which the owner allowed (ADR-0005); both can
break when YouTube changes, so every failure is classified for the job instead of raised raw.

Each function makes one kind of call and returns plain data; budgets and persistence belong to
`letsplays.worker`.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import requests

API = "https://www.googleapis.com/youtube/v3"
# Both queries were in the evaluated pool; either alone scores below the bar (selection_results).
QUERIES = ('"{title}" let\'s play', '"{title}" gameplay')
PER_QUERY = 25
SEARCH_UNITS = 100
VIDEOS_UNITS = 1
CAPTION_WINDOW_SECONDS = 15 * 60
FRAGMENT_SECONDS = 320
FRAGMENT_BYTES = 2_200_000  # ~6 minutes at YouTube's ~48 kbit/s audio-only m4a
DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
# Failures that say nothing about the video: the network, DNS or YouTube refusing this address.
UNREACHABLE = "youtube_unreachable"
NETWORK_CODES = frozenset({UNREACHABLE, "audio_unreachable"})
NETWORK_SIGNS = re.compile(
    r"TransportError|Failed to resolve|timed out|Connection|Unable to download API page|"
    r"HTTP Error 5\d\d",
    re.IGNORECASE,
)
# YouTube refusing this address (bot check, rate limit): every video fails alike, so the whole
# kind pauses instead of each game retrying (met on the service host in YTP-04).
BLOCKED = "youtube_blocked"
BLOCK_SIGNS = re.compile(r"not a bot|HTTP Error 429|Too Many Requests", re.IGNORECASE)


class YouTubeError(Exception):
    """A classified failure: `code` is stored on the job and shown as a reason."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Found:
    video_id: str
    title: str
    channel: str
    published: str
    language: str | None
    live: str | None
    seconds: int
    views: int | None


@dataclass(frozen=True, slots=True)
class VideoFacts:
    """What yt-dlp says about a video: its length and its original audio stream."""

    seconds: int
    language: str | None
    audio_url: str | None


@dataclass(frozen=True, slots=True)
class Heard:
    language: str | None
    text: str
    seconds: float


def _seconds(iso: str) -> int:
    match = DURATION.fullmatch(iso)
    if not match:
        return 0
    days, hours, minutes, secs = (int(part or 0) for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + secs


def _api(client: httpx.Client, path: str, key: str, params: dict[str, str]) -> dict[str, Any]:
    try:
        response = client.get(f"{API}/{path}", params={**params, "key": key})
    except httpx.HTTPError as error:
        raise YouTubeError("youtube_api_unreachable", type(error).__name__) from error
    text = response.text.lower()
    # 403 quotaExceeded (daily units) and 429 rateLimitExceeded ("Search Queries per day", a
    # separate per-method limit met in YTP-04) both mean: no more searches today.
    if response.status_code in (403, 429) and ("quota" in text or "ratelimitexceeded" in text):
        raise YouTubeError("youtube_quota_exceeded", f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise YouTubeError("youtube_api_error", f"HTTP {response.status_code}")
    document = response.json()
    if not isinstance(document, dict):
        raise YouTubeError("youtube_api_error", "unexpected JSON")
    return document


def search_units(found_ids: int) -> int:
    return SEARCH_UNITS * len(QUERIES) + VIDEOS_UNITS * max(1, -(-found_ids // 50))


def search(client: httpx.Client, key: str, title: str) -> list[Found]:
    """Two searches and their statistics: at most `search_units(50)` = 201 API units."""
    ids: list[str] = []
    for query in QUERIES:
        document = _api(
            client,
            "search",
            key,
            {
                "part": "snippet",
                "q": query.format(title=title),
                "type": "video",
                "maxResults": str(PER_QUERY),
                "order": "relevance",
                "safeSearch": "none",
            },
        )
        for item in document.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if isinstance(video_id, str) and video_id not in ids:
                ids.append(video_id)
    found: list[Found] = []
    for start in range(0, len(ids), 50):
        document = _api(
            client,
            "videos",
            key,
            {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[start : start + 50])},
        )
        for video in document.get("items", []):
            snippet, stats = video.get("snippet", {}), video.get("statistics", {})
            found.append(
                Found(
                    video_id=video["id"],
                    title=str(snippet.get("title", ""))[:200],
                    channel=str(snippet.get("channelTitle", ""))[:120],
                    published=str(snippet.get("publishedAt", "")),
                    language=snippet.get("defaultAudioLanguage"),
                    live=snippet.get("liveBroadcastContent"),
                    seconds=_seconds(video.get("contentDetails", {}).get("duration", "")),
                    views=int(stats["viewCount"]) if "viewCount" in stats else None,
                )
            )
    return found


def facts(video_id: str) -> VideoFacts:
    """Length and the original audio stream; an automatic dub is never the original."""
    import yt_dlp

    options = {"quiet": True, "no_warnings": True, "skip_download": True, "cachedir": False}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except yt_dlp.utils.DownloadError as error:
        message = str(error)
        if BLOCK_SIGNS.search(message):
            code = BLOCKED
        elif NETWORK_SIGNS.search(message):
            code = UNREACHABLE
        else:
            code = "video_unavailable"
        raise YouTubeError(code, str(error)[:120]) from error
    if not isinstance(info, dict):
        raise YouTubeError("video_unavailable", "no information")
    streams = [
        fmt
        for fmt in info.get("formats") or []
        if fmt.get("vcodec") == "none" and fmt.get("ext") == "m4a" and fmt.get("url")
    ]
    original = [fmt for fmt in streams if "original" in str(fmt.get("format_note") or "")]
    chosen = min(original or streams, key=lambda fmt: fmt.get("abr") or 1e9, default=None)
    language = (chosen or {}).get("language") or info.get("language")
    return VideoFacts(
        seconds=int(info.get("duration") or 0),
        language=language if isinstance(language, str) else None,
        audio_url=chosen.get("url") if chosen else None,
    )


def captions(video_id: str, language: str | None, video_seconds: int) -> Heard | None:
    """The first 15 minutes of captions in the spoken language, or None when there are none.

    Raises `YouTubeError("captions_blocked")` when YouTube refuses this address; the worker then
    pauses captions and listens to audio instead.
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        CouldNotRetrieveTranscript,
        IpBlocked,
        RequestBlocked,
    )

    try:
        tracks = list(YouTubeTranscriptApi().list(video_id))
        # A generated track is speech recognition in the spoken language; automatic dubs add
        # tracks in other languages, so the original language decides when it is known.
        generated = [track for track in tracks if track.is_generated]
        wanted = (language or "").split("-")[0].lower()
        same = [track for track in generated if track.language_code.split("-")[0] == wanted]
        manual = [
            track
            for track in tracks
            if not track.is_generated and track.language_code.split("-")[0] == wanted
        ]
        choices = same or manual or (generated if not wanted else [])
        if not choices:
            return None
        pick = choices[0]
        parts = [part for part in pick.fetch() if part.start < CAPTION_WINDOW_SECONDS]
    except (IpBlocked, RequestBlocked) as error:
        raise YouTubeError("captions_blocked") from error
    except CouldNotRetrieveTranscript:
        return None
    except requests.RequestException as error:
        raise YouTubeError(UNREACHABLE, type(error).__name__) from error
    covered = min(CAPTION_WINDOW_SECONDS, video_seconds) if video_seconds else 0
    return Heard(pick.language_code, " ".join(part.text for part in parts), float(covered))


def audio_fragment(audio_url: str, client: httpx.Client) -> Path:
    """The first `FRAGMENT_SECONDS` of the original audio, remuxed to its real length.

    A byte-cut m4a still declares the whole video's duration; remuxing writes the true one. The
    caller deletes the returned file.
    """
    import imageio_ffmpeg

    handle, name = tempfile.mkstemp(suffix=".m4a", prefix="letsplay-")
    os.close(handle)  # written below by path; an open descriptor would leak per fragment
    raw = Path(name)
    cut = raw.with_name(raw.stem + "-cut.m4a")
    try:
        try:
            response = client.get(audio_url, headers={"Range": f"bytes=0-{FRAGMENT_BYTES - 1}"})
        except httpx.HTTPError as error:
            raise YouTubeError("audio_unreachable", type(error).__name__) from error
        if response.status_code not in (200, 206):
            raise YouTubeError("audio_refused", f"HTTP {response.status_code}")
        raw.write_bytes(response.content[:FRAGMENT_BYTES])
        result = subprocess.run(  # noqa: S603 - fixed ffmpeg arguments, no shell
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-v",
                "error",
                "-y",
                "-i",
                str(raw),
                "-t",
                str(FRAGMENT_SECONDS),
                "-c",
                "copy",
                str(cut),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0 or not cut.exists() or cut.stat().st_size == 0:
            cut.unlink(missing_ok=True)
            raise YouTubeError("audio_unreadable")
        return cut
    finally:
        raw.unlink(missing_ok=True)


def temp_dir_ready() -> bool:
    """yt-dlp's JavaScript runtime and ffmpeg need a writable temporary directory."""
    return os.access(tempfile.gettempdir(), os.W_OK)
