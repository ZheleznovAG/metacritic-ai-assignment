"""IMP-01: run local migrations with the schema owner's credentials, never web's."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    load_dotenv(ROOT / ".env.app", override=False)
    os.environ["DATABASE_USER"] = os.environ["MIGRATE_DB_USER"]
    os.environ["DATABASE_PASSWORD"] = os.environ["MIGRATE_DB_PASSWORD"]
    subprocess.run(
        [sys.executable, "-B", "app/manage.py", "migrate", "--noinput"], cwd=ROOT, check=True
    )
