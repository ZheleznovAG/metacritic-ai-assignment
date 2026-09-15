"""HRD-05: `python scripts/storage_report.py [--disk-path PATH]`. Read-only (runs under
`WEB_DB_USER`, SELECT-only); prints one JSON report. `--disk-path` should point at the actual
PGDATA/volume mount on a real deployment -- it defaults to the current working directory's
filesystem, which is only meaningful when that happens to share a volume with the database.
"""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from processing.storage_report import storage_report


class Command(BaseCommand):
    help = "Prints a JSON storage report: sizes, text-version/observation/attempt overhead, disk."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--disk-path", default=".", help="Filesystem path to measure headroom on."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = storage_report(disk_path=options["disk_path"])
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
