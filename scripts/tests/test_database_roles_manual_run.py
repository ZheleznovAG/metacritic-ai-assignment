"""BON-22 / R-SEC-01: the exact `grant_manual_run_access.grant()` used in production, exercised
against throwaway tables on the same isolated "metacritic" project as `test_database_roles.py`
(not the real migrated tables -- this runs before `migrate` ever touches that database in CI, the
same ordering constraint `test_database_roles.py` already works within). Real table *names* are
used (grant.py's statements are not parametrized), dropped again before this process exits.
"""

import os
import sys
import unittest
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grant_manual_run_access import grant  # noqa: E402


class ManualRunGrantTests(unittest.TestCase):
    def test_web_gets_exactly_the_narrow_write_access_the_grant_script_names(self) -> None:
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
        with psycopg.connect(
            dbname=database,
            user=os.environ["MIGRATE_DB_USER"],
            password=os.environ["MIGRATE_DB_PASSWORD"],
            **options,
        ) as owner:
            owner.execute(
                "CREATE TABLE django_session (session_key varchar(40) primary key, "
                "session_data text, expire_date timestamptz)"
            )
            owner.execute(
                "CREATE TABLE auth_user (id bigserial primary key, username varchar(150), "
                "last_login timestamptz)"
            )
            owner.execute(
                "CREATE TABLE processing_manualrunrequest (id bigserial primary key, "
                "state varchar(16))"
            )
            owner.execute("CREATE TABLE processing_triggeradmission (id bigserial primary key)")
            owner.execute(
                "CREATE TABLE processing_loginfailure (id bigserial primary key, "
                "fingerprint varchar(128))"
            )
            try:
                # The real `db_grants` service runs as the admin superuser (matching
                # `provision_db.py`'s own convention); this test uses `owner` (the migrate role)
                # instead, since `checks` never receives admin credentials -- and since `owner`
                # created and thus owns these throwaway tables, it can grant on them directly,
                # exercising the exact same `grant()` statements either way.
                grant(owner, os.environ["WEB_DB_USER"])

                with psycopg.connect(dbname=database, **web_options, **options) as web:
                    web.execute("INSERT INTO django_session VALUES ('k', 'v', now())")
                    web.execute("UPDATE django_session SET session_data='w' WHERE session_key='k'")
                    web.execute("DELETE FROM django_session WHERE session_key='k'")

                    owner.execute("INSERT INTO auth_user (username) VALUES ('probe') RETURNING id")
                    uid = owner.execute(
                        "SELECT id FROM auth_user WHERE username='probe'"
                    ).fetchone()[0]
                    web.execute("UPDATE auth_user SET last_login = now() WHERE id=%s", (uid,))
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        web.execute("UPDATE auth_user SET username='x' WHERE id=%s", (uid,))

                    web.execute("INSERT INTO processing_manualrunrequest (state) VALUES ('queued')")
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        web.execute("UPDATE processing_manualrunrequest SET state='claimed'")
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        web.execute("DELETE FROM processing_manualrunrequest")

                    owner.execute("INSERT INTO processing_triggeradmission DEFAULT VALUES")
                    web.execute("UPDATE processing_triggeradmission SET id = id")
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        web.execute("INSERT INTO processing_triggeradmission DEFAULT VALUES")

                    web.execute(
                        "INSERT INTO processing_loginfailure (fingerprint) VALUES ('probe')"
                    )
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        web.execute("DELETE FROM processing_loginfailure")
            finally:
                for table in (
                    "django_session",
                    "auth_user",
                    "processing_manualrunrequest",
                    "processing_triggeradmission",
                    "processing_loginfailure",
                ):
                    owner.execute(f"DROP TABLE IF EXISTS {table}")
