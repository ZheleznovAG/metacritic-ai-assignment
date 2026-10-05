"""FIN-ARCH / R-OPS-01: command discovery, idle priority and failure/resource boundaries."""

import os
from io import StringIO
from unittest.mock import Mock, patch

import httpx
from django.core.management import get_commands
from django.test import SimpleTestCase
from orchestration.management.commands.run_worker import Command
from reviews.models import ReviewCollectionJob

from tests.test_reviews_collector import FakeClock, FakeGateway
from tests.test_reviews_snapshots import NOW


class WorkerOrchestrationTests(SimpleTestCase):
    def setUp(self) -> None:
        self.clock = FakeClock(NOW)
        self.gateway = FakeGateway({})
        self.errors = StringIO()
        self.command = Command(stdout=StringIO(), stderr=self.errors)

    def test_existing_public_command_is_discovered_in_the_composition_root(self) -> None:
        self.assertEqual(get_commands()["run_worker"], "orchestration")

    def test_review_work_does_not_run_idle_maintenance_or_letsplays(self) -> None:
        job = ReviewCollectionJob(id=7, audience="critic", state="pending")
        with (
            patch("orchestration.jobs.claim_next", return_value=job),
            patch(
                "orchestration.management.commands.run_worker.collector.collect_one_page",
                return_value=job,
            ) as collect,
            patch.object(self.command, "_maintain_similar_games") as maintain,
            patch.object(self.command, "_advance_letsplays") as letsplays,
            httpx.Client() as client,
        ):
            self.command._tick(
                self.gateway, client, self.clock, "test-key", "https://api.groq.com/openai/v1"
            )
        collect.assert_called_once_with(self.gateway, self.clock, job)
        maintain.assert_not_called()
        letsplays.assert_not_called()

    def test_idle_without_groq_key_maintains_similarity_but_skips_provider_work(self) -> None:
        with (
            patch("orchestration.jobs.claim_next", return_value=None) as claim,
            patch.object(self.command, "_maintain_similar_games") as maintain,
            patch.object(self.command, "_advance_letsplays") as letsplays,
            httpx.Client() as client,
        ):
            self.command._tick(
                self.gateway, client, self.clock, "", "https://api.groq.com/openai/v1"
            )
        claim.assert_called_once_with(self.clock, summaries_enabled=False)
        maintain.assert_called_once_with(self.clock)
        letsplays.assert_not_called()

    def test_idle_maintenance_precedes_one_letsplay_step(self) -> None:
        calls: list[str] = []

        def maintain(clock: FakeClock) -> None:
            calls.append("similarity")

        def advance(clock: FakeClock) -> bool:
            calls.append("letsplays")
            return True

        with (
            patch("orchestration.jobs.claim_next", return_value=None),
            patch.object(self.command, "_maintain_similar_games", side_effect=maintain),
            patch.object(self.command, "_advance_letsplays", side_effect=advance),
            httpx.Client() as client,
        ):
            self.command._tick(
                self.gateway, client, self.clock, "test-key", "https://api.groq.com/openai/v1"
            )
        self.assertEqual(calls, ["similarity", "letsplays"])

    def test_unexpected_letsplay_failure_is_isolated_and_logs_only_its_type(self) -> None:
        self.command._letsplays = Mock()
        with patch(
            "orchestration.management.commands.run_worker.letsplay_worker.advance",
            side_effect=RuntimeError("private provider details"),
        ):
            self.assertFalse(self.command._advance_letsplays(self.clock))
        self.assertIn("RuntimeError", self.errors.getvalue())
        self.assertNotIn("private provider details", self.errors.getvalue())

    def test_once_closes_both_http_clients_after_success_and_failure(self) -> None:
        for error in (None, RuntimeError("fixture tick failure")):
            with self.subTest(error=error):
                with (
                    patch.dict(
                        os.environ,
                        {
                            "GROQ_API_KEY": "",
                            "YOUTUBE_API_KEY": "",
                            "GROQ_API_BASE_URL": "https://api.groq.com/openai/v1",
                        },
                    ),
                    patch(
                        "orchestration.management.commands.run_worker.ObservedGateway"
                    ) as gateway,
                    patch("orchestration.management.commands.run_worker.httpx.Client") as client,
                    patch("orchestration.management.commands.run_worker.Maintainer"),
                    patch("orchestration.management.commands.run_worker.Heartbeat"),
                    patch.object(self.command, "_tick", side_effect=error) as tick,
                ):
                    if error:
                        with self.assertRaisesRegex(RuntimeError, "fixture tick failure"):
                            self.command.handle(once=True)
                    else:
                        self.command.handle(once=True)
                    tick.assert_called_once()
                    gateway.return_value.close.assert_called_once()
                    client.return_value.close.assert_called_once()
