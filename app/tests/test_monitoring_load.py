"""BON-21: fixed-volume, ten-observer acceptance on the disposable checks database."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from catalog.models import Game
from django.db import connection, connections
from django.test import Client, TransactionTestCase
from django.utils import timezone
from processing.models import ProcessingRun
from reviews.models import ReviewCorpus
from summaries.models import SummaryJob


class MonitoringLoadTests(TransactionTestCase):
    def test_ten_observers_with_ten_thousand_runs_and_one_hundred_thousand_jobs(self) -> None:
        now = timezone.now()
        game = Game.objects.create(
            source_game_id="load", canonical_locator="/game/load/", title="Load fixture"
        )
        corpus = ReviewCorpus.objects.create(
            game=game,
            audience="user",
            policy_version="load",
            source_set_fingerprint="a" * 64,
            model_input_fingerprint="b" * 64,
            complete_route_count=0,
            empty_route_count=0,
            reported_count=0,
            fetched_count=0,
            unique_count=0,
            deduplicated_count=0,
            selected_count=0,
            tokenizer_id="fixture",
            tokenizer_version="1",
            raw_prompt_tokens=0,
            guarded_prompt_tokens=0,
            completion_reservation=0,
        )
        ProcessingRun.objects.bulk_create(
            [
                ProcessingRun(trigger_key=f"load:{i}", scheduled_slot=now, status="succeeded")
                for i in range(10_000)
            ],
            batch_size=1000,
        )
        for start in range(0, 100_000, 2000):
            SummaryJob.objects.bulk_create(
                [
                    SummaryJob(
                        game=game,
                        audience="user",
                        source_corpus=corpus,
                        input_fingerprint=f"{i:064x}",
                        contour_fingerprint="c" * 64,
                        state="pending" if i % 2 else "succeeded",
                    )
                    for i in range(start, start + 2000)
                ]
            )
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE processing_processingrun")
            cursor.execute("ANALYZE summaries_summaryjob")
            cursor.execute(
                "EXPLAIN (ANALYZE, BUFFERS) SELECT state, count(id), min(created_at) "
                "FROM summaries_summaryjob GROUP BY state"
            )
            plan = [row[0] for row in cursor.fetchall()]
        gate = Barrier(10)

        def observer() -> list[float]:
            timings = []
            try:
                client = Client()
                for _ in range(3):
                    gate.wait(timeout=15)
                    started = time.monotonic()
                    response = client.get("/ops/status/")
                    timings.append(time.monotonic() - started)
                    self.assertEqual(response.status_code, 200)
                    self.assertLess(len(response.content), 64 * 1024)
                    self.assertEqual(response.json()["summaries"]["outstanding"], 50_000)
                    self.assertEqual(client.get("/?q=Load").status_code, 200)
                    time.sleep(max(0, 1 - (time.monotonic() - started)))
            finally:
                connections.close_all()
            return timings

        cpu_start = time.process_time()
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: observer(), range(10)))
        timings = sorted(value for result in results for value in result)
        evidence = {
            "runs": 10_000,
            "jobs": 100_000,
            "observers": 10,
            "snapshots": len(timings),
            "max_seconds": round(max(timings), 4),
            "p95_seconds": round(timings[28], 4),
            "wall_seconds": round(time.monotonic() - started, 4),
            "application_cpu_seconds": round(time.process_time() - cpu_start, 4),
            "summary_query_plan": plan,
        }
        folder = os.environ.get("E2E_ARTIFACT_DIR")
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / "bon21-load.json").write_text(
                json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
            )
        self.assertLess(max(timings), 1.0, evidence)
