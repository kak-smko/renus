from __future__ import annotations

from collections.abc import Callable
from typing import Any

from renus.router.chain import (
    EndpointFunc,
    MiddlewareFunc,
    is_onion_middleware,
    run_middleware_chain,
)

LegacyMiddlewareFunc = Callable[[Any], Any]

class Middleware:
    """Wrap a chain of legacy middlewares around a request."""

    def __init__(
        self, request: Any, middlewares: list[LegacyMiddlewareFunc] | None = None
    ) -> None:
        """Create a middleware chain wrapper.

        Parameters
        ----------
        request:
            The current request to pass to each middleware.
        middlewares:
            Optional list of legacy middlewares to run.
        """
        self.middlewares: list[LegacyMiddlewareFunc] = (
            [] if middlewares is None else middlewares
        )
        self.request: Any = request

    def next(self) -> Any:
        """Return the first non-``True`` middleware result, or ``True``."""
        for middleware in self.middlewares:
            handle = middleware(self.request)
            if handle is True:
                continue
            return handle
        return True

    __call__ = next

__all__ = [
    "EndpointFunc",
    "LegacyMiddlewareFunc",
    "Middleware",
    "MiddlewareFunc",
    "is_onion_middleware",
    "run_middleware_chain",
]
