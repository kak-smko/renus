from __future__ import annotations

import datetime
from typing import Final

from .state import Spec, interval_delta

_AT_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "weeks": ("day", "hour", "minute", "second"),
    "days": ("hour", "minute", "second"),
    "hours": ("minute", "second"),
    "minutes": ("second",),
    "seconds": (),
}

_FORGET_COLUMN: Final[dict[str, str]] = {
    "days": "day",
    "hours": "hour",
    "minutes": "minute",
    "seconds": "second",
}

def _now_fields(now: datetime.datetime) -> dict[str, object]:
    return {
        "day": now.strftime("%A"),
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
    }

def is_due(
    key: str,
    last_run: dict[str, datetime.datetime],
    now: datetime.datetime,
    spec: Spec,
) -> bool:
    """Return whether the job is due to run under ``spec``."""
    if spec.unit not in _AT_COLUMNS:
        return False
    if key not in last_run:
        return True
    return last_run[key] < now - interval_delta(spec.unit, spec.interval)

def matches(spec: Spec, now: datetime.datetime) -> bool:
    """Return whether ``now`` matches ``spec``'s schedule and forget rules."""
    if spec.unit not in _AT_COLUMNS:
        return False
    fields = _now_fields(now)

    for column in _AT_COLUMNS[spec.unit]:
        wanted = getattr(spec.at, column)
        if wanted is not None and wanted != fields[column]:
            return False

    skip = _FORGET_COLUMN.get(spec.unit)
    if skip is not None:
        forbidden = getattr(spec.forget, skip)
        if forbidden is not None and fields[skip] in forbidden:
            return False

    return True
