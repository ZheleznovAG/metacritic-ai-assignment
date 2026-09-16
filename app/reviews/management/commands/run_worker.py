"""IMP-04 real worker entry point: `python scripts/run_worker.py [--once]`.

One tick advances a review page or a summary attempt, alternating due queues durably. The
summary queue is enabled when credentials are configured. Matches `docs/design.md`:
"worker последовательно выполняет два вида сохранённой enrichment-работы" — one process, two job
types, no Celery/Redis.
"""

import os
import time
from typing import Any

import httpx
from django.core.management.base import BaseCommand, CommandParser
from metacritic.gateway import ReviewGatewayProtocol
from processing.clock import Clock, SystemClock
from processing.heartbeat import Heartbeat, report_progress
from processing.observed_gateway import ObservedGateway
from summaries import groq_adapter
from summaries import worker as summary_worker

from reviews import collector, dispatch
from reviews.models import ReviewCollectionJob

POLL_INTERVAL_SECONDS = 5


class Command(BaseCommand):
    help = "Claims and advances one review-collection page or one summary-job attempt per tick."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true", help="Run a single tick and exit.")

    def handle(self, *args: Any, **options: Any) -> None:
        clock = SystemClock()
        gateway = ObservedGateway()
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        base_url = groq_adapter.validate_base_url(
            os.environ.get("GROQ_API_BASE_URL", groq_adapter.DEFAULT_BASE_URL)
        )
        timeout = float(os.environ.get("GROQ_API_TIMEOUT_SECONDS", "180"))
        client = httpx.Client(timeout=timeout)
        try:
            with Heartbeat("worker"):
                if options["once"]:
                    self._tick(gateway, client, clock, api_key, base_url)
                    return
                while True:
                    self._tick(gateway, client, clock, api_key, base_url)
                    report_progress("idle")
                    time.sleep(POLL_INTERVAL_SECONDS)
        finally:
            gateway.close()
            client.close()

    def _tick(
        self,
        gateway: ReviewGatewayProtocol,
        client: httpx.Client,
        clock: Clock,
        api_key: str,
        base_url: str,
    ) -> None:
        report_progress("claiming", deadline_seconds=5)
        job = dispatch.claim_next(clock, summaries_enabled=bool(api_key))
        if isinstance(job, ReviewCollectionJob):
            report_progress("reviews", job_id=job.pk, deadline_seconds=300)
            updated_review_job = collector.collect_one_page(gateway, clock, job)
            self.stdout.write(
                self.style.SUCCESS(
                    f"review_job_id={updated_review_job.id} audience={updated_review_job.audience} "
                    f"state={updated_review_job.state} page={updated_review_job.page_count} "
                    f"fetched={updated_review_job.fetched_count}"
                )
            )
            return

        if not api_key:
            self.stdout.write(
                "idle: no review work due (GROQ_API_KEY not set, skipping summary work)"
            )
            return

        if job is not None:
            report_progress("summary", job_id=job.pk, deadline_seconds=300)
            updated_summary_job = summary_worker.process_job(
                client, clock, job, api_key=api_key, base_url=base_url
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"summary_job_id={updated_summary_job.id} "
                    f"audience={updated_summary_job.audience} state={updated_summary_job.state}"
                )
            )
            return

        self.stdout.write("idle: no review or summary work due")
