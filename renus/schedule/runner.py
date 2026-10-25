from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable
from traceback import format_exception
from typing import Any

from renus.log import Log

def thread_exception_handler(exc: tuple[type[BaseException], BaseException, Any]) -> None:
    """Log the exception raised by a background thread."""
    Log().error(
        "schedule failed at: "
        f"{exc[1]!s} - "
        f"{format_exception(exc[0], exc[1], exc[2])}"
    )

def run_threaded(job_func: Callable[[], None]) -> None:
    """Run the job function in a background thread."""
    threading.excepthook = thread_exception_handler
    t = threading.Thread(target=job_func)
    t.start()

def run_with_retry(
    job_func: Callable[[], None],
    *,
    max_try: int,
    parallel: bool = True,
) -> None:
    """Run the job, retrying until ``max_try`` attempts are reached."""
    attempt = 0
    while True:
        try:
            if parallel:
                run_threaded(job_func)
            else:
                job_func()
            return
        except Exception:
            attempt += 1
            if attempt < max_try:
                continue
            raise


async def run_with_retry_async(
    job_func: Callable[[], Any],
    *,
    max_try: int,
    parallel: bool = True,
) -> None:
    """Run a sync or async job and retry failures up to ``max_try`` times."""
    attempt = 0
    while True:
        try:
            is_async_callable = inspect.iscoroutinefunction(
                job_func
            ) or inspect.iscoroutinefunction(getattr(job_func, "__call__", None))
            if parallel and not is_async_callable:
                result = await asyncio.to_thread(job_func)
            else:
                result = job_func()
            if inspect.isawaitable(result):
                await result
            return
        except Exception:
            attempt += 1
            if attempt < max_try:
                continue
            raise
