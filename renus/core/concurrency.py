import functools
import typing
from typing import Any, AsyncGenerator, Iterator

import anyio

T = typing.TypeVar("T")


async def run_in_threadpool(
        func: typing.Callable[..., T], *args: typing.Any, **kwargs: typing.Any
) -> T:
    if kwargs:  # pragma: no cover
        # run_sync doesn't accept 'kwargs', so bind them in here
        func = functools.partial(func, **kwargs)
    return await anyio.to_thread.run_sync(func, *args)


class _StopIteration(Exception):
    pass


def _next(iterator: Iterator) -> Any:
    # We can't raise `StopIteration` from within the threadpool iterator
    # and catch it outside that context, so we coerce them into a different
    # exception type.
    try:
        return next(iterator)
    except StopIteration:
        raise _StopIteration


async def iterate_in_threadpool(iterator: Iterator) -> AsyncGenerator:
    while True:
        try:
            yield await anyio.to_thread.run_sync(_next, iterator)
        except _StopIteration:
            break
