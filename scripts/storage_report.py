"""HRD-05 storage report entry point: `python scripts/storage_report.py [--disk-path PATH]`.
Uses the read-only web role (SELECT only, the same one the public preview runs under) --
reporting can only read, never write.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    load_dotenv(ROOT / ".env.app", override=False)
    os.environ["DATABASE_USER"] = os.environ["WEB_DB_USER"]
    os.environ["DATABASE_PASSWORD"] = os.environ["WEB_DB_PASSWORD"]
    subprocess.run(
        [sys.executable, "-B", "app/manage.py", "storage_report", *sys.argv[1:]],
        cwd=ROOT,
        check=True,
    )
