"""Same fail-fast checks locally and in CI; IMP-01 / NFR-06, no external calls."""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    load_dotenv(ROOT / ".env.app", override=False)
    if os.environ.get("APP_ENV") == "production":
        raise SystemExit("Checks refuse APP_ENV=production")
    if os.environ.get("APP_ENV") != "test":
        os.environ["POSTGRES_DB"] += "_checks"
        os.environ["DATABASE_USER"] = os.environ["CHECKS_DB_USER"]
        os.environ["DATABASE_PASSWORD"] = os.environ["CHECKS_DB_PASSWORD"]
        os.environ["APP_ENV"] = "test"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # Django's mypy plugin imports application settings.
    os.environ["PYTHONPATH"] = str(ROOT / "app")
    commands = [
        ["-m", "ruff", "format", "--check", "app", "scripts"],
        ["-m", "ruff", "check", "app", "scripts"],
        ["-m", "mypy"],
        ["app/manage.py", "check"],
        ["app/manage.py", "makemigrations", "--check", "--dry-run"],
        ["app/manage.py", "collectstatic", "--noinput"],
        ["app/manage.py", "test", "tests", "--noinput", "-v", "2"],
        ["-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_*.py"],
        ["research/planning/check_plan.py"],
        ["-m", "unittest", "discover", "-s", "research/planning", "-p", "test_*.py"],
        ["evals/reviews/score_run.py", "evals/reviews/baseline/run.json", "--verify"],
        ["-m", "unittest", "discover", "-s", "evals/reviews", "-p", "test_*.py"],
    ]
    for arguments in commands:
        print("CHECK:", " ".join(arguments), flush=True)
        subprocess.run([sys.executable, "-B", *arguments], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
