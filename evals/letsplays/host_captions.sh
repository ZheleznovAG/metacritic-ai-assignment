#!/bin/sh
# YTP-02: read the first 15 minutes of captions for the videos that decide the
# frozen labels. Runs on the service host in a throwaway container (no database,
# no service network, removed on exit) and needs no key. Output is JSONL with
# third-party text: redirect it to .artifacts/, never into Git.
#
#   ssh <host> sh -s < evals/letsplays/host_captions.sh > .artifacts/ytp02/captions.jsonl
set -eu
docker run --rm -i python:3.12-slim sh -c '
pip install -q --root-user-action=ignore youtube-transcript-api==1.2.4 >/dev/null 2>&1
python - <<"EOF"
import json, sys, time
from youtube_transcript_api import YouTubeTranscriptApi

WINDOW = 15 * 60
IDS = """
GWomHd7hlFk dn5_p5jaJn0 7H9oZSbxWrk H4j5H_g-qeU 5RE1GwL_XIQ qaGrShDlH48
ekxWBkP6ULU AnDPvHCujmI i9vo2SZwhMY iKyXn73EDs8 TZ6Sex25Fro HsPQyKS8vG0
N84q1nzOuUw NVHr_-5nzeE yN8Z26N_qDE Nh3ph9qGac4 nZhtL22UfjI YQnC7ky6d24
nv3PxdX3w2s EAHi7-atB2U WbCSp1Buwu8 4wPvpOOaXOU WxiqIJVOiaw 3VPNJxjPOew
qguZahH8AwI a_E8OGLlwc8 _bvkLBN8HyU GvkHybmubjQ PN7YFKHOR9Y ZIQtxEoGts4
""".split()
api = YouTubeTranscriptApi()
for vid in IDS:
    row = {"video_id": vid}
    try:
        tracks = list(api.list(vid))
        row["tracks"] = [[t.language_code, t.is_generated] for t in tracks]
        # The generated track is speech recognition in the spoken language;
        # manual tracks may be translations.
        generated = [t for t in tracks if t.is_generated]
        track = (generated or tracks)[0]
        parts = [s for s in track.fetch() if s.start < WINDOW]
        text = " ".join(s.text for s in parts)
        spoken = [w for w in text.split() if not w.startswith("[")]
        row.update(language=track.language_code, generated=track.is_generated,
                   words=len(spoken), text=text)
    except Exception as error:
        row["error"] = type(error).__name__
    print(json.dumps(row, ensure_ascii=False), flush=True)
    time.sleep(4)
EOF
'
