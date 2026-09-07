#!/usr/bin/env python3
"""Persist one sanitised SPK-06 scheduler event atomically."""

from __future__ import annotations

import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


PROBE_NAME = "metacritic-ai-spk06"
PROBE_ROOT = Path(__file__).resolve().parent
PUBLIC_ROOT = PROBE_ROOT / "public"
STATE_PATH = PUBLIC_ROOT / "state.json"
LOCK_PATH = PROBE_ROOT / "state.lock"
ALLOWED_ORIGINS = {"manual", "hourly"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state() -> dict[str, object]:
    if not STATE_PATH.exists():
        return {
            "probe": PROBE_NAME,
            "schema_version": 1,
            "counter": 0,
            "scheduled_counter": 0,
        }
    with STATE_PATH.open("r", encoding="utf-8") as stream:
        state = json.load(stream)
    if state.get("probe") != PROBE_NAME or state.get("schema_version") != 1:
        raise ValueError("unexpected probe state")
    return state


def save_state(state: dict[str, object]) -> None:
    PUBLIC_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = STATE_PATH.with_name(f".{STATE_PATH.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(state, stream, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, STATE_PATH)


def main() -> int:
    origin = sys.argv[1] if len(sys.argv) == 2 else "manual"
    if origin not in ALLOWED_ORIGINS:
        raise ValueError("origin must be manual or hourly")

    PROBE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with LOCK_PATH.open("a", encoding="utf-8") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        state = load_state()
        state["counter"] = int(state.get("counter", 0)) + 1
        if origin == "hourly":
            state["scheduled_counter"] = int(state.get("scheduled_counter", 0)) + 1
        state.update(
            {
                "last_event_origin": origin,
                "last_event_utc": utc_now(),
                "last_outcome": "succeeded",
                "last_run_id": uuid.uuid4().hex,
            }
        )
        save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
