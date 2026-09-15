"""HRD-05: storage measurement that reports real overhead beyond unique review text --
`implementation_plan.md#hrd-05` explicitly rules out an O(unique reviews) approximation. Runs on
whatever database Django is configured against; against a representative production corpus that
is `PUB-02`'s live-measurement scope (`docs/design.md`'s repeated live-vs-CI boundary), not
duplicated here -- this module and its tests only prove the report itself measures the right
things correctly, deterministically, in CI.
"""

from __future__ import annotations

import shutil
from typing import Any

from catalog.models import Game, SourceFetch
from django.db import connection, transaction
from reviews.models import Review, ReviewCorpusItem, ReviewObservation
from summaries.models import SummaryAttempt, SummaryJob

# Storage-relevant tables, largest expected growth first. Read from each model's own `db_table`
# rather than hardcoded strings, so a future rename can't silently desync this report.
_MEASURED_MODELS = (Review, ReviewObservation, SourceFetch, SummaryAttempt, ReviewCorpusItem, Game)


def _table_size_bytes(table: str) -> int | None:
    # A nested `atomic()` opens a SAVEPOINT when already inside a transaction (true for every
    # Django `TestCase`, and for any future caller run inside one), so a failed query here rolls
    # back only to that savepoint instead of aborting the whole surrounding transaction -- without
    # it, the caller's *next* query would fail with a misleading "current transaction is aborted"
    # instead of ever seeing this function's own handled, swallowed error.
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT pg_total_relation_size(%s)", [table])
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001 - a missing/renamed table degrades, not crashes, a report
        return None
    return int(row[0]) if row and row[0] is not None else None


def _database_size_bytes() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        row = cursor.fetchone()
        return int(row[0])


def _wal_size_bytes() -> int | None:
    """`pg_ls_waldir()` needs superuser/`pg_monitor`; the read-only reporting role deliberately
    does not have it (least privilege), so this degrades to `None` rather than failing the whole
    report. Runs in its own savepoint (see `_table_size_bytes`) so the expected permission-denied
    error here can never poison a surrounding transaction."""
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(size), 0) FROM pg_ls_waldir()")
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001 - permission-denied is expected under the web role
        return None
    return int(row[0]) if row and row[0] is not None else None


def _disk_headroom_bytes(path: str) -> dict[str, int]:
    usage = shutil.disk_usage(path)
    return {"total": usage.total, "used": usage.used, "free": usage.free}


def storage_report(*, disk_path: str = ".") -> dict[str, Any]:
    review_count = Review.objects.count()
    distinct_identity_keys = Review.objects.values("identity_key").distinct().count()
    observation_count = ReviewObservation.objects.count()
    attempt_count = SummaryAttempt.objects.count()
    terminal_job_count = SummaryJob.objects.filter(
        state__in=("succeeded", "insufficient_data", "failed")
    ).count()

    table_sizes = {
        model._meta.db_table: _table_size_bytes(model._meta.db_table) for model in _MEASURED_MODELS
    }
    return {
        "database_size_bytes": _database_size_bytes(),
        "table_sizes_bytes": table_sizes,
        "wal_size_bytes": _wal_size_bytes(),
        "disk": _disk_headroom_bytes(disk_path),
        "text_versions": {
            "review_rows": review_count,
            "distinct_identities": distinct_identity_keys,
            # >1 means the same identity has more than one saved text version (an edited review
            # re-observed with a changed version_sha256); this is the overhead an O(unique
            # reviews) estimate would miss entirely.
            "versions_per_identity": (
                round(review_count / distinct_identity_keys, 3) if distinct_identity_keys else None
            ),
        },
        "repeated_observations": {
            "review_rows": review_count,
            "observation_rows": observation_count,
            # >1 means the same review text was observed again across more than one collection
            # generation/page acceptance -- storage this report must not silently drop.
            "observations_per_review": (
                round(observation_count / review_count, 3) if review_count else None
            ),
        },
        "attempts": {
            "attempt_rows": attempt_count,
            "terminal_job_rows": terminal_job_count,
            "attempts_per_terminal_job": (
                round(attempt_count / terminal_job_count, 3) if terminal_job_count else None
            ),
        },
    }
