import inspect

from renus.cache import Cache

def resolve_handler(res, request):
    """Resolve the callable handler for a route result.

    Parameters
    ----------
    res:
        The matched route record.
    request:
        The current request, passed to the controller if needed.
    """
    if res["controller"] is None:
        return res["func"]
    args = inspect.getfullargspec(res["controller"].__init__).args
    controller = (
        res["controller"](request) if "request" in args else res["controller"]()
    )
    return getattr(controller, res["func"])

def build_endpoint(res, method, request):
    """Build a cached endpoint if the route enables caching.

    Parameters
    ----------
    res:
        The matched route record.
    method:
        The resolved handler function.
    request:
        The current request.
    """
    if not res["cache"]:
        return method

    async def dispatch(**kwargs):
        return await method(**kwargs)

    async def cached(**kwargs):

        c = Cache().get(request.path, None)
        if c is not None:
            c.raw_headers.append((b"r-cache", b"ok"))
            return c
        r = await dispatch(**kwargs)
        Cache().put(request.path, r, res["cache"])
        return r

    return cached

async def run_direct(res, request, method):
    """Run a resolved handler directly.

    Parameters
    ----------
    res:
        The matched route record.
    request:
        The current request.
    method:
        The resolved handler function.
    """
    endpoint = build_endpoint(res, method, request)
    return await endpoint(**res["args"])

def resolve_routes(registry, req, scope):
    """Resolve the matching route for a request or scope.

    Parameters
    ----------
    req:
        The request or websocket object.
    scope:
        The ASGI scope.
    """
    return registry.resolve(req, scope)
