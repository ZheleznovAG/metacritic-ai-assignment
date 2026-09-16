"""BON-21 process telemetry, independent of HTTP and of all work/lease decisions."""

import logging
from contextvars import ContextVar, Token
from datetime import datetime, timedelta
from threading import Event, Lock, Thread
from types import TracebackType
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.db import DatabaseError, connections, transaction

from processing.clock import Clock, SystemClock
from processing.models import ProcessHeartbeat

logger = logging.getLogger(__name__)
_current: ContextVar["Heartbeat | None"] = ContextVar("process_heartbeat", default=None)
STALE_SECONDS = 3


def report_progress(
    stage: str,
    *,
    run_id: int | None = None,
    job_id: int | None = None,
    deadline_seconds: float | None = None,
) -> None:
    observer = _current.get()
    if observer is not None:
        observer.activity(stage, run_id=run_id, job_id=job_id, deadline_seconds=deadline_seconds)


class Heartbeat:
    def __init__(
        self,
        role: str,
        *,
        slot: str = "main",
        clock: Clock | None = None,
        interval: float = 1.0,
    ) -> None:
        self.role = role
        self.clock = clock or SystemClock()
        self.interval = interval
        self.instance_id = uuid4()
        self.generation = 0
        self.slot = slot
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._token: Token[Heartbeat | None] | None = None
        self._values: dict[str, Any] = {}
        self.activity("idle")

    def activity(
        self,
        stage: str,
        *,
        run_id: int | None = None,
        job_id: int | None = None,
        deadline_seconds: float | None = None,
    ) -> None:
        now = self.clock.now_utc()
        with self._lock:
            self._values = {
                "mode": "idle" if stage == "idle" else "busy",
                "stage": stage,
                "run_id": None if stage == "idle" else run_id or self._values.get("run_id"),
                "job_id": None if stage == "idle" else job_id or self._values.get("job_id"),
                "last_progress_at": now,
                "deadline_at": now + timedelta(seconds=deadline_seconds)
                if deadline_seconds is not None
                else None,
            }

    def register(self) -> None:
        now = self.clock.now_utc()
        with transaction.atomic():
            row, created = ProcessHeartbeat.objects.get_or_create(
                role=self.role,
                slot=self.slot,
                defaults={
                    "instance_id": self.instance_id,
                    "started_at": now,
                    "last_seen_at": now,
                    "last_progress_at": now,
                },
            )
            row = ProcessHeartbeat.objects.select_for_update().get(pk=row.pk)
            generation = row.generation if created else row.generation + 1
            ProcessHeartbeat.objects.filter(pk=row.pk).update(
                instance_id=self.instance_id,
                generation=generation,
                started_at=now,
                last_seen_at=now,
                **self._values,
            )
        # A failed transaction must leave registration retryable by the background loop.
        self.generation = generation

    def publish(self, *, stopped: bool = False) -> bool:
        with self._lock:
            values = dict(self._values)
        if stopped:
            values.update(mode="stopped", stage="stopped", deadline_at=None)
        return bool(
            ProcessHeartbeat.objects.filter(
                role=self.role,
                slot=self.slot,
                instance_id=self.instance_id,
                generation=self.generation,
            ).update(last_seen_at=self.clock.now_utc(), **values)
        )

    def _loop(self) -> None:
        # Django connections are thread-local. Never borrow the main processing transaction.
        connection = connections["default"]
        try:
            while not self._stop.is_set():
                try:
                    if not self.generation:
                        self.register()
                    with connection.cursor() as cursor:
                        cursor.execute("SET statement_timeout = 800")
                        cursor.execute("SET lock_timeout = 500")
                    if not self.publish():
                        break  # A newer instance owns this observation slot.
                except DatabaseError:
                    connection.close()
                    logger.warning("Process telemetry temporarily unavailable")
                if self._stop.wait(self.interval):
                    break
            try:
                if self.generation:
                    self.publish(stopped=True)
            except DatabaseError:
                pass  # The public observer will classify the last heartbeat as stale.
        finally:
            connection.close()

    def __enter__(self) -> "Heartbeat":
        if settings.OPS_MONITORING_ENABLED:
            self._token = _current.set(self)
            self._thread = Thread(target=self._loop, name=f"{self.role}-heartbeat", daemon=True)
            self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._token is not None:
            _current.reset(self._token)


def process_state(last_seen_at: datetime, mode: str, now: datetime) -> str:
    if mode == "stopped":
        return "stopped"
    if (now - last_seen_at).total_seconds() > STALE_SECONDS:
        return "stale"
    return mode if mode in {"idle", "busy"} else "unknown"
