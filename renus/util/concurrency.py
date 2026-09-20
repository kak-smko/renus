from __future__ import annotations

import asyncio
import atexit
import functools
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from typing import Any, TypeVar

from anyio.to_thread import run_sync

T = TypeVar("T")


class _StopIteration(Exception):
    pass

def _next(iterator: Iterator[T]) -> T:
    try:
        return next(iterator)
    except StopIteration:
        raise _StopIteration

async def run_in_threadpool(
    func: Callable[..., T], *args: Any, **kwargs: Any
) -> T:
    """Run a synchronous callable in a worker thread and await its result.

    Parameters
    ----------
    func:
        Callable to execute.
    args:
        Positional arguments passed to ``func``.
    kwargs:
        Keyword arguments passed to ``func``.
    """
    if kwargs:
        func = functools.partial(func, **kwargs)
    return await run_sync(func, *args)

async def iterate_in_threadpool(
    iterator: Iterator[T] | AsyncIterator[T],
) -> AsyncGenerator[T, None]:
    """Iterate an iterator in a worker thread, yielding items asynchronously.

    Parameters
    ----------
    iterator:
        Sync or async iterator to consume.
    """
    if hasattr(iterator, "__anext__"):
        async for item in iterator:
            yield item
        return
    while True:
        try:
            yield await run_sync(_next, iterator)
        except _StopIteration:
            break

_process_executor: ProcessPoolExecutor | None = None

def _get_process_executor() -> ProcessPoolExecutor:
    global _process_executor
    if _process_executor is None:
        _process_executor = ProcessPoolExecutor()
        atexit.register(_process_executor.shutdown)
    return _process_executor

async def run_in_processpool(
    func: Callable[..., T], *args: Any, **kwargs: Any
) -> T:
    """Run a synchronous callable in a process pool and await its result.

    Parameters
    ----------
    func:
        Callable to execute.
    args:
        Positional arguments passed to ``func``.
    kwargs:
        Keyword arguments passed to ``func``.
    """
    if kwargs:
        func = functools.partial(func, **kwargs)
    return await asyncio.wrap_future(_get_process_executor().submit(func, *args))

def shutdown_pool() -> None:
    """Shut down the shared process pool executor."""
    global _process_executor
    if _process_executor is not None:
        executor = _process_executor
        _process_executor = None
        executor.shutdown()
