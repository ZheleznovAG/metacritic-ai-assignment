"""IMP-04 real worker entry point, using the dedicated worker role (SELECT/INSERT/UPDATE only, no
DDL). Pass `--once` for a single tick; omit it for a continuous loop. Reads Groq credentials from
the operator `.env` (never committed), same discipline as `evals/reviews/run_groq_eval.py`.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    load_dotenv(ROOT / ".env.app", override=False)
    load_dotenv(ROOT / ".env", override=False)
    os.environ["DATABASE_USER"] = os.environ["WORKER_DB_USER"]
    os.environ["DATABASE_PASSWORD"] = os.environ["WORKER_DB_PASSWORD"]
    subprocess.run(
        [sys.executable, "-B", "app/manage.py", "run_worker", *sys.argv[1:]],
        cwd=ROOT,
        check=True,
    )
