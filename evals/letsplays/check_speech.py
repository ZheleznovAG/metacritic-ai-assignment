"""YTP-02 labelling aid: what is spoken at the start of a video's original audio?

Downloads the first bytes of the smallest original-language m4a stream with
yt-dlp and sends them to Groq Whisper. Prints JSONL with third-party text:
redirect it to .artifacts/, never into Git. Used only where captions could not
decide a label (blocked, disabled, or an automatic dub was the only track).

    python evals/letsplays/check_speech.py --env .env VIDEO_ID ... > .artifacts/ytp02/speech.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

import yt_dlp

FRAGMENT_BYTES = 2_000_000  # ~5.5 minutes at YouTube's ~48 kbit/s m4a
# A byte-truncated m4a keeps the full video duration in its header; remuxing
# writes the real length. A precaution: Groq's audio-seconds accounting was not
# explained by either length (see metric.md).
FRAGMENT_SECONDS = 320
MODEL = "whisper-large-v3-turbo"
ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"


def groq_key(env_file: str) -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key and env_file:
        with open(env_file, encoding="utf-8") as handle:
            for line in handle:
                name, _, value = line.strip().partition("=")
                if name == "GROQ_API_KEY":
                    key = value.strip().strip('"').strip("'")
    if not key:
        sys.exit("GROQ_API_KEY is not set")
    return key


def original_audio(video_id: str) -> dict:
    options: dict = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    streams = [
        fmt
        for fmt in info["formats"]
        if fmt.get("vcodec") == "none" and fmt.get("ext") == "m4a" and fmt.get("url")
    ]
    # Automatic dubs are extra audio tracks; the original is marked as such.
    original = [fmt for fmt in streams if "original" in (fmt.get("format_note") or "")]
    chosen = min(original or streams, key=lambda fmt: fmt.get("abr") or 1e9)
    return {"stream": chosen, "dubbed_tracks": len({f.get("language") for f in streams}) > 1}


def remux(raw: str) -> str:
    import imageio_ffmpeg

    out = raw.replace(".m4a", ".cut.m4a")
    subprocess.run(  # noqa: S603 - fixed ffmpeg arguments
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-y",
            "-i",
            raw,
            "-t",
            str(FRAGMENT_SECONDS),
            "-c",
            "copy",
            out,
        ],
        check=True,
    )
    return out


def transcribe(path: str, key: str) -> dict:
    config = f'header = "Authorization: Bearer {key}"\n'
    result = subprocess.run(  # noqa: S603 - fixed curl arguments, key passed on stdin
        [
            "curl",
            "-sS",
            "-K",
            "-",
            ENDPOINT,
            "-F",
            f"model={MODEL}",
            "-F",
            "response_format=verbose_json",
            "-F",
            f"file=@{path};type=audio/mp4",
        ],
        input=config,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="")
    parser.add_argument("videos", nargs="+")
    args = parser.parse_args()
    key = groq_key(args.env)
    sys.stdout.reconfigure(encoding="utf-8")
    for video_id in args.videos:
        row: dict = {"video_id": video_id}
        try:
            audio = original_audio(video_id)
            stream = audio["stream"]
            request = urllib.request.Request(  # noqa: S310 - https URL from yt-dlp
                stream["url"], headers={"Range": f"bytes=0-{FRAGMENT_BYTES - 1}"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                data = response.read()
            with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as handle:
                handle.write(data)
            cut = ""
            try:
                cut = remux(handle.name)
                reply = transcribe(cut, key)
            finally:
                for path in (handle.name, cut):
                    if path and os.path.exists(path):
                        os.unlink(path)
            text = reply.get("text", "")
            row.update(
                stream_language=stream.get("language"),
                stream_note=stream.get("format_note"),
                dubbed_tracks=audio["dubbed_tracks"],
                whisper_language=reply.get("language"),
                seconds=reply.get("duration"),
                words=len(text.split()),
                text=text,
                error=reply.get("error"),
            )
        except Exception as error:  # noqa: BLE001 - the aid records any failure class
            row["error"] = f"{type(error).__name__}: {str(error)[:200]}"
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
