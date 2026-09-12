from renus.app.handlers import resolve_routes
from renus.request import Request
from renus.response import JsonResponse, Response, Status, TextResponse, debug_response
from renus.router import run_middleware_chain
from renus.websockets import WebSocket

_MUTATING_METHODS = frozenset(("POST", "PUT", "DELETE"))

async def serve_http(app, scope, receive, send) -> None:
    """Serve an HTTP request through the app.

    Parameters
    ----------
    app:
        The application instance.
    scope, receive, send:
        The ASGI connection parameters.
    """
    scope["method"] = scope["method"].upper()
    request = Request(scope, receive)

    try:
        await serve_view(app, request, scope, receive, send)
    except Exception as exc:
        debug = debug_response(exc, app.debug)
        await serve_result(
            app, request, JsonResponse(*debug), scope, receive, send
        )
        if app.env == "local":
            raise

async def serve_view(app, request, scope, receive, send) -> None:
    """Resolve routes and dispatch a view for the request.

    Parameters
    ----------
    app:
        The application instance.
    request:
        The current request.
    scope, receive, send:
        The ASGI connection parameters.
    """
    res = resolve_routes(request, scope)
    setattr(request, "route", res)

    if not res:
        await serve_result(
            app,
            request,
            TextResponse("Path not Found", Status.HTTP_404_NOT_FOUND),
            scope,
            receive,
            send,
        )
        return

    method = app._resolve_handler(res, request)
    middlewares = app.middlewares + res["middlewares"]

    if "request" in method.__code__.co_varnames:
        res["args"]["request"] = request

    if not middlewares and not res["cache"]:
        r = await method(**res["args"])
        await serve_result(app, request, r, scope, receive, send)
        return

    endpoint = app._endpoint(res, method, request)

    r = await run_middleware_chain(request, middlewares, res, endpoint)
    await serve_result(app, request, r, scope, receive, send)

async def serve_result(app, request, response, scope, receive, send) -> None:
    """Send a response to the client.

    Parameters
    ----------
    app:
        The application instance.
    request:
        The current request.
    response:
        The response to send.
    scope, receive, send:
        The ASGI connection parameters.
    """
    if not isinstance(response, Response):
        response = TextResponse(response)
    await response(request, scope, receive, send)

async def serve_websocket(app, scope, receive, send) -> None:
    """Serve a websocket connection through the app.

    Parameters
    ----------
    app:
        The application instance.
    scope, receive, send:
        The ASGI connection parameters.
    """
    scope["method"] = "WS"
    ws = WebSocket(scope, receive, send)

    try:
        res = resolve_routes(ws, scope)
        setattr(ws, "route", res)
        if not res:
            await ws.close(1004)
        elif res["controller"] is None and not callable(res["func"]):
            await ws.close(1004)
        else:
            method = app._resolve_handler(res, ws)
            res["args"]["ws"] = ws

            async def ws_endpoint(**kwargs):
                await method(**kwargs)
                return True

            middlewares = app.middlewares + res["middlewares"]
            passed = await run_middleware_chain(ws, middlewares, res, ws_endpoint)
            if passed is not True:
                await ws.close(1003)

    except Exception as exc:
        debug_response(exc, app.debug)
        if app.env == "local":
            raise
