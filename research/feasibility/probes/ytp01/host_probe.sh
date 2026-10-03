#!/bin/sh
# YTP-01 host probe: can this host's IP read YouTube captions and audio?
#
# Runs in a throwaway container (no database, no service network, removed on
# exit) and needs no API key: it checks fixed video ids already chosen by
# probe_youtube.py. Usage on the host:  sh host_probe.sh  (or pipe via ssh).
set -eu
docker run --rm -i python:3.12-slim sh -c '
pip install -q --root-user-action=ignore "yt-dlp[default]" youtube-transcript-api deno >/dev/null 2>&1
python - <<"EOF"
import json, time, urllib.request
from importlib.metadata import version
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

IDS = ["z15Pz-50mcc", "I167S6HZcWI", "5C0LQAoFWDY", "2MfJKsplJ4A", "NWgQcKESOg0"]
print("tools", {n: version(n) for n in ("yt-dlp", "youtube-transcript-api", "deno")})
ip = urllib.request.urlopen("https://ipinfo.io/org", timeout=15).read().decode().strip()
print("egress org", ip)
for vid in IDS:
    row = {"video": vid}
    try:
        track = next(iter(YouTubeTranscriptApi().list(vid)))
        row["captions"] = "ok %d segments" % len(track.fetch())
    except Exception as e:
        row["captions"] = type(e).__name__
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
            info = y.extract_info("https://www.youtube.com/watch?v=" + vid, download=False)
        audio = [f for f in info["formats"] if f.get("vcodec") == "none" and f.get("ext") == "m4a" and f.get("url")]
        f = min(audio, key=lambda f: f.get("abr") or 1e9)
        t = time.monotonic()
        req = urllib.request.Request(f["url"], headers={"Range": "bytes=0-3999999"})
        size = len(urllib.request.urlopen(req, timeout=60).read())
        row["audio"] = "ok %d bytes in %.1fs (%s kbps)" % (size, time.monotonic() - t, f.get("abr"))
    except Exception as e:
        row["audio"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    print(json.dumps(row))
    time.sleep(3)
EOF
'
