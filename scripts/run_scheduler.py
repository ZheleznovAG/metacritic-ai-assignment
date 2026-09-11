"""IMP-03 real scheduler entry point, using the dedicated scheduler role (SELECT/INSERT/UPDATE
only, no DDL). Pass `--once` for a single tick; omit it for a continuous loop.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    load_dotenv(ROOT / ".env.app", override=False)
    os.environ["DATABASE_USER"] = os.environ["SCHEDULER_DB_USER"]
    os.environ["DATABASE_PASSWORD"] = os.environ["SCHEDULER_DB_PASSWORD"]
    subprocess.run(
        [sys.executable, "-B", "app/manage.py", "run_scheduler", *sys.argv[1:]],
        cwd=ROOT,
        check=True,
    )
