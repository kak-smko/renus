from __future__ import annotations

import asyncio
from typing import Any, Callable

from renus.util.concurrency import run_in_threadpool

BgFunc = Callable[..., Any]

class Background:
    """Wrap a callable to be executed as a background task."""

    __slots__ = ("_args", "_kwargs", "func", "is_async")

    def __init__(self, func: BgFunc, *args: Any, **kwargs: Any) -> None:
        """Store a callable and its arguments for later execution.

        Parameters
        ----------
        func:
            The callable to run in the background.
        *args:
            Positional arguments passed to ``func``.
        **kwargs:
            Keyword arguments passed to ``func``.
        """
        self.func = func
        self._args = args
        self._kwargs = kwargs
        self.is_async: bool = asyncio.iscoroutinefunction(func)

    async def run(self) -> Any:
        """Execute the wrapped callable, awaiting coroutines."""
        if self.is_async:
            return await self.func(*self._args, **self._kwargs)
        return await run_in_threadpool(self.func, *self._args, **self._kwargs)

    async def __call__(self) -> None:
        """Run the wrapped callable when invoked directly."""
        await self.run()

    def __repr__(self) -> str:
        """Return a string representation of the background task."""
        return f"{type(self).__name__}({self.func!r})"
