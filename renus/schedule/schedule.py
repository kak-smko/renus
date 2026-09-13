from __future__ import annotations
import datetime
import functools
import threading
from collections.abc import Callable
from typing import Any

from renus.cache import Cache
from renus.log import Log

from .matcher import is_due, matches
from .runner import run_with_retry
from .state import Spec, TZ_OFFSET

_LAST_RUN_KEY: str = "schedule_last_run"
_LAST_RUN_TTL: int = 24 * 60 * 60

class Schedule:
    """A fluent builder for defining and running scheduled jobs."""

    def __init__(self) -> None:
        """Initialize a schedule with a fresh spec and no registered jobs."""
        self._spec = Spec()
        self._job_list: dict[str, Callable[[], None]] = {}
        self._last_run: dict = Cache().get(_LAST_RUN_KEY, {})
        self._locks: dict[str, threading.Lock] = {}

    def timedelta(self, n: int) -> Schedule:
        """Set the time adjustment applied to job runs."""
        self._spec.timedelta = n
        return self

    def every(self, n: int = 1) -> Schedule:
        """Reset the spec and set the run interval to ``n`` units."""
        self._spec = Spec()
        self._spec.interval = n
        return self

    def weeks(self) -> Schedule:
        """Schedule jobs to run on a weekly basis."""
        self._spec.unit = "weeks"
        return self

    def days(self) -> Schedule:
        """Schedule jobs to run on a daily basis."""
        self._spec.unit = "days"
        return self

    def hours(self) -> Schedule:
        """Schedule jobs to run on an hourly basis."""
        self._spec.unit = "hours"
        return self

    def minutes(self) -> Schedule:
        """Schedule jobs to run on a per-minute basis."""
        self._spec.unit = "minutes"
        return self

    def seconds(self) -> Schedule:
        """Schedule jobs to run on a per-second basis."""
        self._spec.unit = "seconds"
        return self

    def max_try(self, n: int) -> Schedule:
        """Set the maximum run attempts for a job."""
        self._spec.max_try = n
        return self

    def at(
        self,
        day: str | None = None,
        hour: int | None = None,
        minute: int | None = None,
        secound: int | None = None,
    ) -> Schedule:
        """Target the job at specific day, hour, minute, and second."""
        self._spec.at.day = day
        self._spec.at.hour = hour
        self._spec.at.minute = minute
        self._spec.at.second = secound
        return self

    def forget(
        self,
        days: list | None = None,
        hours: list | None = None,
        minutes: list | None = None,
        seconds: list | None = None,
    ) -> Schedule:
        """Skip the job on the given days, hours, minutes, or seconds."""
        self._spec.forget.day = days
        self._spec.forget.hour = hours
        self._spec.forget.minute = minutes
        self._spec.forget.second = seconds
        return self

    def do(self, key: str, func: Callable, *args: Any, **kwargs: Any) -> None:
        """Register ``func`` as a job under ``key`` when it is due to run."""
        now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=self._spec.timedelta
        )

        job_func = functools.partial(func, *args, **kwargs)
        try:
            functools.update_wrapper(job_func, func)
        except AttributeError:
            pass

        if (
            is_due(key, self._last_run, now, self._spec)
            and matches(self._spec, now)
        ):
            self._job_list[key] = job_func

    def job(
        self,
        key: str,
        func: Callable[[], None],
        parallel: bool = True,
    ) -> None:
        """Execute the job for ``key`` now, waiting for any running instance."""
        now = datetime.datetime.now(datetime.timezone.utc) + TZ_OFFSET
        self._last_run[key] = now
        Cache().put(_LAST_RUN_KEY, self._last_run, _LAST_RUN_TTL)
        self._job_list.pop(key, None)
        lock = self._locks.setdefault(key, threading.Lock())
        if parallel:
            threading.Thread(
                target=self._run_job, args=(key, func, self._spec.max_try, now, lock)
            ).start()
        else:
            self._run_job(key, func, self._spec.max_try, now, lock)

    def _run_job(
        self,
        key: str,
        func: Callable[[], None],
        max_try: int,
        now: datetime.datetime,
        lock: threading.Lock,
    ) -> None:
        with lock:
            try:
                run_with_retry(func, max_try=max_try, parallel=False)
                Log().info(f"schedule job {key} at: {now!s}")
            except Exception as exc:
                Log().error(f"schedule failed [{key}] at: {now!s} - {exc!s}")

    def run(self, parallel: bool = True) -> None:
        """Execute all registered jobs."""
        for key, func in list(self._job_list.items()):
            self.job(key, func, parallel)
