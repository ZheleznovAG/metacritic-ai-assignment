"""`docs/design.md` `Clock.now_utc()` interface; a fake implementation is injected in tests."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(tz=UTC)
