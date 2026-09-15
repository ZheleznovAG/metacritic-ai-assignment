"""HRD-05 operator diagnostics entry point: `python scripts/diagnose.py --run <id>` (also
`--game <id>`, `--job review|summary <id>`, `--backlog`). Uses the read-only web role (SELECT
only, the same one the public preview runs under) -- diagnostics can only read, never write.
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
        [sys.executable, "-B", "app/manage.py", "diagnose", *sys.argv[1:]],
        cwd=ROOT,
        check=True,
    )
