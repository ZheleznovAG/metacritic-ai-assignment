"""IMP-01: provision separate database roles; also supports the existing empty scaffold."""

import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql


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


def provision() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.app", override=False)
    database = identifier("POSTGRES_DB")
    admin = identifier("POSTGRES_USER")
    web = identifier("WEB_DB_USER")
    migrate = identifier("MIGRATE_DB_USER")
    scheduler = identifier("SCHEDULER_DB_USER")
    worker = identifier("WORKER_DB_USER")
    mode = required("APP_ENV")
    if mode not in {"local", "test", "production"}:
        raise ValueError("Unknown APP_ENV")
    with_checks = mode in {"local", "test"}
    roles = [
        (web, required("WEB_DB_PASSWORD"), False),
        (migrate, required("MIGRATE_DB_PASSWORD"), False),
        (scheduler, required("SCHEDULER_DB_PASSWORD"), False),
        (worker, required("WORKER_DB_PASSWORD"), False),
    ]
    if with_checks:
        roles.append((identifier("CHECKS_DB_USER"), required("CHECKS_DB_PASSWORD"), True))
    if len({admin, *(role[0] for role in roles)}) != len(roles) + 1:
        raise ValueError("Administrative, web, migration and checks roles must differ")
    options = dict(
        host=required("POSTGRES_HOST"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=admin,
        password=required("POSTGRES_PASSWORD"),
        connect_timeout=3,
    )
    with psycopg.connect(dbname=database, **options) as connection:
        # Refuse an unplanned ownership conversion of an older product database.
        legacy = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tableowner=%s",
            (admin,),
        ).fetchall()
        if any(row[0] != "django_migrations" for row in legacy):
            raise ValueError("Legacy product tables need a separate ownership migration")
        # Password-bearing utility statements must never enter server error logs.
        connection.execute("SET log_statement = 'none'")
        connection.execute("SET log_min_error_statement = 'panic'")
        for name, password, can_create_db in roles:
            present = connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)
            ).fetchone()
            if present:
                membership = connection.execute(
                    "SELECT 1 FROM pg_auth_members WHERE member="
                    "(SELECT oid FROM pg_roles WHERE rolname=%s)",
                    (name,),
                ).fetchone()
                if membership:
                    raise ValueError("Existing application role has unexpected memberships")
            verb = sql.SQL("ALTER ROLE" if present else "CREATE ROLE")
            create_db = sql.SQL("CREATEDB" if can_create_db else "NOCREATEDB")
            connection.execute(
                sql.SQL(
                    "{} {} LOGIN NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS {} PASSWORD {}"
                ).format(verb, sql.Identifier(name), create_db, sql.Literal(password))
            )
        connection.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(database), sql.Identifier(migrate)
            )
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM {}").format(
                sql.Identifier(database), sql.Identifier(web)
            )
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(web)
            )
        )
        connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        connection.execute(
            sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(sql.Identifier(web))
        )
        connection.execute(
            sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(migrate))
        )
        if legacy:
            connection.execute(
                sql.SQL("ALTER TABLE public.django_migrations OWNER TO {}").format(
                    sql.Identifier(migrate)
                )
            )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(web))
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(sql.Identifier(web))
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(
                sql.Identifier(web)
            )
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(web))
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public REVOKE ALL ON TABLES FROM {}"
            ).format(sql.Identifier(migrate), sql.Identifier(web))
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}"
            ).format(sql.Identifier(migrate), sql.Identifier(web))
        )
        # scheduler (IMP-03) writes application rows but never DDL: SELECT/INSERT/UPDATE only,
        # no DELETE (nothing in this codebase deletes rows) and no schema ownership.
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(scheduler)
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(scheduler))
        )
        connection.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(scheduler)
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                sql.Identifier(scheduler)
            )
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE ON TABLES TO {}"
            ).format(sql.Identifier(migrate), sql.Identifier(scheduler))
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(sql.Identifier(migrate), sql.Identifier(scheduler))
        )
        # worker (IMP-04) collects review pages and drives AI summary jobs: same least-privilege
        # shape as scheduler (SELECT/INSERT/UPDATE only, no DELETE, no DDL).
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(worker)
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(worker))
        )
        connection.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {}").format(
                sql.Identifier(worker)
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                sql.Identifier(worker)
            )
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE ON TABLES TO {}"
            ).format(sql.Identifier(migrate), sql.Identifier(worker))
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(sql.Identifier(migrate), sql.Identifier(worker))
        )
    if with_checks:
        checks = roles[-1][0]
        checks_database = database + "_checks"
        with psycopg.connect(dbname="postgres", autocommit=True, **options) as connection:
            existing = connection.execute(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s",
                (checks_database,),
            ).fetchone()
            if existing and existing[0] != checks:
                raise ValueError("Existing checks database has a different owner")
            if not existing:
                connection.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(checks_database), sql.Identifier(checks)
                    )
                )
            connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(checks_database)
                )
            )
    print("Database roles provisioned; web is read-only, credentials are not printed.")


if __name__ == "__main__":
    try:
        provision()
    except (ValueError, psycopg.Error) as error:
        # PostgreSQL exceptions may include statements or connection metadata.
        raise SystemExit(
            f"Database provisioning failed ({type(error).__name__}); "
            "check configuration and ownership."
        ) from None
