"""Minimal bounded diagnostics: never log arbitrary exception/request text."""

import json
import logging


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "logger": record.name[:100],
                "event": "application_log",
                "status_code": getattr(record, "status_code", None),
                "exception_type": (
                    record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None
                ),
            }
        )
