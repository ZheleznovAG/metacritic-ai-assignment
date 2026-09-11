"""IMP-02 one-off proof run, using schema-owner credentials since no worker role exists yet.

`IMP-03` replaces this with a real scheduler/worker process and a dedicated write role.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python scripts/ingest_game.py <https://www.metacritic.com/game/...>"
        )
    load_dotenv(ROOT / ".env.app", override=False)
    os.environ["DATABASE_USER"] = os.environ["MIGRATE_DB_USER"]
    os.environ["DATABASE_PASSWORD"] = os.environ["MIGRATE_DB_PASSWORD"]
    subprocess.run(
        [sys.executable, "-B", "app/manage.py", "ingest_game", sys.argv[1]], cwd=ROOT, check=True
    )
