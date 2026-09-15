"""Shared harness for real-thread PostgreSQL concurrency tests (HRD-03).

`TestCase` wraps each test in one transaction on one connection, where two genuinely concurrent
claimants can never occur; proving a `select_for_update()` claim actually serializes real
concurrent transactions needs real threads with their own DB connections, synchronized to start
at (as close as the OS scheduler allows) the same instant.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from django.db import connections


def run_concurrently[T](
    *targets: Callable[[], T | None], timeout: float = 10
) -> tuple[list[T | None], list[BaseException]]:
    """Runs each target in its own thread, synchronized with a `threading.Barrier` so they all
    start together, each on its own DB connection (closed on exit, regardless of outcome).
    Returns each target's return value (`None` for one that raised) and any exceptions raised,
    in target order. Callers assert on both: an empty exception list, and however many `None`s
    are expected among the results."""
    barrier = threading.Barrier(len(targets))
    results: list[T | None] = [None for _ in targets]
    errors: list[BaseException] = []

    def run(index: int, target: Callable[[], T | None]) -> None:
        try:
            barrier.wait(timeout=timeout)
            results[index] = target()
        except BaseException as error:  # noqa: BLE001 - surfaced to the caller's own assertions
            errors.append(error)
        finally:
            connections.close_all()

    threads = [
        threading.Thread(target=run, args=(index, target)) for index, target in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=timeout)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError("a concurrency test thread did not finish within the timeout")
    return results, errors
