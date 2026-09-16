"""BON-22: narrow web write-allowlist for the manual-run trigger.

`provision_db.py` runs before `migrate` (roles must exist first) and only ever grants web a
blanket read-only `SELECT`, via `ALTER DEFAULT PRIVILEGES`, on tables that do not exist yet. The
few tables BON-22 needs web to *write* (its own sessions, its own manual-run command rows, the
admission rate-limit lock, its own login-failure audit rows, and one column of `auth_user`) can
only be named after `migrate` has created them, so this runs as its own step afterward. Every
grant here is by exact table (and one by exact column); nothing broadens the existing blanket
grants. Idempotent: safe to rerun on every deploy.
"""

import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

REQUIRED_TABLES = (
    "django_session",
    "auth_user",
    "processing_manualrunrequest",
    "processing_triggeradmission",
    "processing_loginfailure",
)


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ValueError(f"Missing setting: {name}")
    return value


def identifier(name: str) -> str:
    value = required(name)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", value):
        raise ValueError(f"Invalid database identifier: {name}")
    return value


def grant(connection: psycopg.Connection, web: str) -> None:
    web_ident = sql.Identifier(web)
    # Web owns its own session lifecycle end to end (login creates/refreshes, logout deletes).
    connection.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON django_session TO {}").format(web_ident)
    )
    # Django's `user_logged_in` signal writes only this one column on a successful login.
    connection.execute(sql.SQL("GRANT UPDATE (last_login) ON auth_user TO {}").format(web_ident))
    # Web only ever inserts a new command row; the scheduler alone claims/transitions/closes it.
    connection.execute(
        sql.SQL("GRANT INSERT ON processing_manualrunrequest TO {}").format(web_ident)
    )
    connection.execute(
        sql.SQL("GRANT USAGE, SELECT ON processing_manualrunrequest_id_seq TO {}").format(web_ident)
    )
    # The admission singleton row: web locks/reads it (never inserts -- a migration seeds it) to
    # serialize its own rate-limit decisions.
    connection.execute(
        sql.SQL("GRANT UPDATE ON processing_triggeradmission TO {}").format(web_ident)
    )
    # Login-throttle audit rows: web inserts its own failures and counts them; never updates.
    connection.execute(sql.SQL("GRANT INSERT ON processing_loginfailure TO {}").format(web_ident))
    connection.execute(
        sql.SQL("GRANT USAGE, SELECT ON processing_loginfailure_id_seq TO {}").format(web_ident)
    )


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.app", override=False)
    database = identifier("POSTGRES_DB")
    admin = identifier("POSTGRES_USER")
    web = identifier("WEB_DB_USER")
    options = dict(
        host=required("POSTGRES_HOST"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=admin,
        password=required("POSTGRES_PASSWORD"),
        connect_timeout=3,
    )
    with psycopg.connect(dbname=database, **options) as connection:
        # Password-bearing utility statements must never enter server error logs.
        connection.execute("SET log_statement = 'none'")
        connection.execute("SET log_min_error_statement = 'panic'")
        missing = [
            table
            for table in REQUIRED_TABLES
            if not connection.execute(
                "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=%s", (table,)
            ).fetchone()
        ]
        if missing:
            raise ValueError(f"Tables missing (run migrate first): {', '.join(missing)}")
        grant(connection, web)
    print("Manual-run write allowlist granted to web; no other privileges changed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, psycopg.Error) as error:
        raise SystemExit(
            f"Manual-run access grant failed ({type(error).__name__}); check configuration."
        ) from None
