"""BON-22: a short, separate polling cycle for operator-triggered manual runs (`docs/
bonus2_design.md`), sharing the same core execution as the hourly scheduler tick but running
independently of it -- the hourly timer must keep working even while a manual batch is mid-flight
across an hour boundary, so this is its own thread with its own DB connection, the same idiom as
`processing.heartbeat.Heartbeat`.
"""

import logging
from datetime import timedelta
from threading import Event, Thread
from types import TracebackType

from django.db import DatabaseError, connections
from metacritic.gateway import GatewayProtocol

from processing.admission import expire_stale
from processing.clock import Clock
from processing.heartbeat import Heartbeat, report_progress
from processing.models import ManualRunRequest
from processing.scheduler import run_manual

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 1.0
QUEUE_TTL = timedelta(minutes=5)


class Dispatcher:
    """`docs/bonus2_design.md`: 'Scheduler проверяет queued commands не реже раза в секунду.'"""

    def __init__(self, gateway: GatewayProtocol, clock: Clock) -> None:
        self.gateway = gateway
        self.clock = clock
        self._stop = Event()
        self._thread: Thread | None = None

    def _tick(self) -> None:
        expire_stale(self.clock, QUEUE_TTL)
        candidate = (
            ManualRunRequest.objects.filter(state__in=("queued", "claimed"))
            .order_by("created_at")
            .values_list("pk", flat=True)
            .first()
        )
        if candidate is not None:
            report_progress("claiming", job_id=candidate, deadline_seconds=200)
            run_manual(self.gateway, self.clock, candidate)
            report_progress("idle")

    def _loop(self) -> None:
        # Django connections are thread-local; this thread must never borrow the main scheduler
        # tick's connection (or vice versa) while either holds a transaction open. A separate
        # `slot` keeps this thread's own Heartbeat row from racing the hourly tick's: both would
        # otherwise overwrite the same `mode`/`stage`/`run_id` while genuinely running at once
        # (a manual batch mid-flight across an hour boundary, `docs/bonus2_design.md`). Entering
        # it *here*, inside this thread's own run, is what makes `report_progress` calls made
        # while executing a manual run (via `ObservedGateway`) reach this heartbeat: `ContextVar`
        # bindings are not inherited by new `threading.Thread`s.
        connection = connections["default"]
        try:
            with Heartbeat("scheduler", slot="manual-dispatcher"):
                while not self._stop.is_set():
                    try:
                        self._tick()
                    except DatabaseError:
                        connection.close()
                        logger.warning("Manual-run dispatcher tick temporarily unavailable")
                    if self._stop.wait(POLL_INTERVAL_SECONDS):
                        break
        finally:
            connection.close()

    def __enter__(self) -> "Dispatcher":
        self._thread = Thread(target=self._loop, name="manual-dispatcher", daemon=True)
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
