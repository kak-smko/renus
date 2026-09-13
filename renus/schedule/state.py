from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

DEFAULT_INTERVAL: Final[int] = 1
DEFAULT_MAX_TRY: Final[int] = 3

DEFAULT_TIMEDELTA: Final[int] = 0

TZ_OFFSET: Final[datetime.timedelta] = datetime.timedelta(hours=3, minutes=30)

_INTERVAL_DELTAS: Final[dict[str, Callable[[int], datetime.timedelta]]] = {
    "weeks": lambda n: datetime.timedelta(weeks=n),
    "days": lambda n: datetime.timedelta(days=n),
    "hours": lambda n: datetime.timedelta(hours=n),
    "minutes": lambda n: datetime.timedelta(minutes=n),
    "seconds": lambda n: datetime.timedelta(seconds=n),
}

def interval_delta(unit: str, interval: int) -> datetime.timedelta:
    """Return the timedelta for ``interval`` of the given ``unit``."""
    return _INTERVAL_DELTAS[unit](interval)

@dataclass
class At:
    """Target time constraints for a scheduled job."""

    day: str | None = None
    hour: int | None = None
    minute: int | None = None
    second: int | None = None

@dataclass
class Forget:
    """Days, hours, minutes, or seconds on which to skip a job."""

    day: list | None = None
    hour: list | None = None
    minute: list | None = None
    second: list | None = None

@dataclass
class Spec:
    """Configuration describing when and how a scheduled job runs."""

    interval: int = DEFAULT_INTERVAL
    max_try: int = DEFAULT_MAX_TRY
    timedelta: int = DEFAULT_TIMEDELTA
    unit: str | None = None
    at: At = field(default_factory=At)
    forget: Forget = field(default_factory=Forget)
