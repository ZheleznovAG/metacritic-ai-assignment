"""IMP-01 / R-SEC-01: real permission boundaries on the isolated PostgreSQL project."""

import os
import unittest
import uuid

import psycopg
from psycopg import sql


class DatabaseRoleTests(unittest.TestCase):
    def test_web_reads_but_cannot_write_or_administer(self):
        self.assertEqual(os.environ.get("APP_ENV"), "test")
        checks_database = os.environ["POSTGRES_DB"]
        self.assertTrue(checks_database.endswith("_checks"))
        database = checks_database.removesuffix("_checks")
        options = dict(
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"],
            connect_timeout=3,
            autocommit=True,
        )
        web_options = dict(user=os.environ["WEB_DB_USER"], password=os.environ["WEB_DB_PASSWORD"])
        table = sql.Identifier("imp01_probe_" + uuid.uuid4().hex)
        with psycopg.connect(
            dbname=database,
            user=os.environ["MIGRATE_DB_USER"],
            password=os.environ["MIGRATE_DB_PASSWORD"],
            **options,
        ) as owner:
            owner.execute(sql.SQL("CREATE TABLE {} (value integer)").format(table))
            try:
                owner.execute(sql.SQL("INSERT INTO {} VALUES (42)").format(table))
                with psycopg.connect(dbname=database, **web_options, **options) as web:
                    row = web.execute(
                        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                        "rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    ).fetchone()
                    self.assertEqual(row, (False, False, False, False, False))
                    self.assertEqual(
                        web.execute(sql.SQL("SELECT value FROM {}").format(table)).fetchone(), (42,)
                    )
                    for statement in (
                        sql.SQL("INSERT INTO {} VALUES (99)").format(table),
                        sql.SQL("DROP TABLE {}").format(table),
                        sql.SQL("CREATE TEMP TABLE denied (value integer)"),
                    ):
                        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                            web.execute(statement)
                with self.assertRaises(psycopg.OperationalError):
                    psycopg.connect(dbname=checks_database, **web_options, **options)
                with self.assertRaises(psycopg.OperationalError):
                    psycopg.connect(
                        dbname=database,
                        user=os.environ["DATABASE_USER"],
                        password=os.environ["DATABASE_PASSWORD"],
                        **options,
                    )
            finally:
                owner.execute(sql.SQL("DROP TABLE {}").format(table))

    def test_background_roles_can_upsert_but_cannot_delete_or_administer(self):
        self.assertEqual(os.environ.get("APP_ENV"), "test")
        checks_database = os.environ["POSTGRES_DB"]
        self.assertTrue(checks_database.endswith("_checks"))
        database = checks_database.removesuffix("_checks")
        options = dict(
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"],
            connect_timeout=3,
            autocommit=True,
        )
        for role in ("SCHEDULER", "WORKER"):
            with self.subTest(role=role):
                login = dict(
                    user=os.environ[f"{role}_DB_USER"],
                    password=os.environ[f"{role}_DB_PASSWORD"],
                )
                table = sql.Identifier("imp01_probe_" + uuid.uuid4().hex)
                with psycopg.connect(
                    dbname=database,
                    user=os.environ["MIGRATE_DB_USER"],
                    password=os.environ["MIGRATE_DB_PASSWORD"],
                    **options,
                ) as owner:
                    owner.execute(sql.SQL("CREATE TABLE {} (value integer)").format(table))
                    try:
                        with psycopg.connect(dbname=database, **login, **options) as background:
                            row = background.execute(
                                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
                                "rolbypassrls FROM pg_roles WHERE rolname=current_user"
                            ).fetchone()
                            self.assertEqual(row, (False, False, False, False, False))
                            background.execute(sql.SQL("INSERT INTO {} VALUES (42)").format(table))
                            background.execute(sql.SQL("UPDATE {} SET value=43").format(table))
                            self.assertEqual(
                                background.execute(
                                    sql.SQL("SELECT value FROM {}").format(table)
                                ).fetchall(),
                                [(43,)],
                            )
                            for statement in (
                                sql.SQL("DELETE FROM {}").format(table),
                                sql.SQL("DROP TABLE {}").format(table),
                                sql.SQL("CREATE TEMP TABLE denied (value integer)"),
                            ):
                                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                                    background.execute(statement)
                        with self.assertRaises(psycopg.OperationalError):
                            psycopg.connect(dbname=checks_database, **login, **options)
                    finally:
                        owner.execute(sql.SQL("DROP TABLE {}").format(table))
