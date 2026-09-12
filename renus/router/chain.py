from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

EndpointFunc = Callable[..., Any]

MiddlewareFunc = Callable[..., Any]

def is_onion_middleware(middleware: Any) -> bool:
    """Return whether a middleware uses the onion (3+ positional) signature."""
    try:
        signature = inspect.signature(middleware)
    except (TypeError, ValueError):
        return False
    positional = sum(
        1
        for param in signature.parameters.values()
        if param.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY)
    )
    return positional >= 3

async def run_middleware_chain(
    request: Any,
    middlewares: list[MiddlewareFunc],
    res: dict,
    endpoint: EndpointFunc,
) -> Any:
    """Run the middleware chain and invoke the endpoint.

    Parameters
    ----------
    request:
        The current request.
    middlewares:
        Middlewares to apply before the endpoint.
    res:
        Resolved route data dict.
    endpoint:
        Final handler to call.
    """
    if not middlewares:
        return await endpoint(**res["args"])
    handler: EndpointFunc = endpoint
    for middleware in reversed(middlewares):
        handler = _wrap(middleware, request, res, handler)
    return await handler(**res["args"])

def _wrap(middleware: Any, request: Any, res: dict, handler: EndpointFunc) -> EndpointFunc:
    if is_onion_middleware(middleware):
        return _wrap_onion(middleware, request, res, handler)
    return _wrap_legacy(middleware, request, handler)

def _wrap_onion(
    middleware: Any, request: Any, res: dict, handler: EndpointFunc
) -> EndpointFunc:

    async def onion_handle(**kwargs: Any) -> Any:
        return await middleware(request, handler, res)

    return onion_handle

def _wrap_legacy(
    middleware: Any, request: Any, handler: EndpointFunc
) -> EndpointFunc:

    async def legacy_handle(**kwargs: Any) -> Any:
        result = middleware(request)
        if inspect.isawaitable(result):
            result = await result
        if result is not True:
            return result
        return await handler(**kwargs)

    return legacy_handle

__all__ = [
    "EndpointFunc",
    "MiddlewareFunc",
    "is_onion_middleware",
    "run_middleware_chain",
]
