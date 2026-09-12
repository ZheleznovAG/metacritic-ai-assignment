import json
import logging
from unittest.mock import patch

from config.safe_logging import SafeFormatter
from django.conf import settings
from django.db import OperationalError, connection
from django.test import TestCase


class PublicScaffoldTests(TestCase):
    def test_index_states_actual_scope(self) -> None:
        response = self.client.get("/")
        self.assertContains(response, "not implemented yet")
        self.assertContains(response, settings.APP_VERSION)
        self.assertIn("no-store", response["Cache-Control"])

    def test_live_has_only_safe_fields(self) -> None:
        response = self.client.get("/health/live/")
        self.assertEqual(response.json(), {"status": "ok", "version": settings.APP_VERSION})
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")

    def test_unknown_host_is_rejected(self) -> None:
        self.assertEqual(self.client.get("/", HTTP_HOST="attacker.invalid").status_code, 400)

    def test_no_mutating_routes(self) -> None:
        for path in ("/", "/health/live/", "/health/ready/"):
            self.assertEqual(self.client.post(path).status_code, 405)
        for path in ("/admin/", "/.env", "/.env.app", "/trigger/", "/unknown"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_database_error_is_sanitised(self) -> None:
        with patch("presentation.views.connection") as database:
            database.cursor.side_effect = OperationalError("secret")
            response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_logs_do_not_disclose_request_or_exception_text(self) -> None:
        record = logging.LogRecord("django.request", logging.ERROR, "", 1, "secret", (), None)
        formatted = SafeFormatter().format(record)
        self.assertNotIn("secret", formatted)
        self.assertEqual(json.loads(formatted)["event"], "application_log")


class PostgresReadinessTests(TestCase):
    def test_readiness_uses_actual_postgres_16(self) -> None:
        self.assertEqual(connection.vendor, "postgresql")
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            row = cursor.fetchone()
            assert row is not None
            self.assertEqual(int(row[0]) // 10000, 16)
            cursor.execute("SHOW timezone")
            self.assertEqual(cursor.fetchone(), ("UTC",))
        self.assertEqual(self.client.get("/health/ready/").status_code, 200)
