import inspect
import traceback

def build_default_lifespan(app):
    """Build the default lifespan context manager for an app.

    Parameters
    ----------
    app:
        The application instance.
    """
    async def default_lifespan(_app):
        from renus.cache import Cache

        await Cache.connect_all()
        try:
            await run_startup(app)
            yield
        finally:
            try:
                await run_shutdown(app)
            finally:
                await Cache.disconnect_all()

    return default_lifespan

async def _consume_result(result) -> None:
    if result is None:
        return
    if inspect.isasyncgen(result):
        async for _ in result:
            pass
        return
    if inspect.isawaitable(result):
        await result
        return

def _call_handler(app, handler, *, on_startup: bool):
    try:
        args = set(inspect.signature(handler).parameters)
    except (TypeError, ValueError):
        args = set()
    kwargs = {'app': app, 'on_startup': on_startup} if args else {}
    return handler(**kwargs)

async def run_startup(app) -> None:
    """Run all registered startup handlers.

    Parameters
    ----------
    app:
        The application instance.
    """
    for handler in app.on_startup:
        await _consume_result(_call_handler(app, handler, on_startup=True))

async def run_shutdown(app) -> None:
    """Run all registered shutdown handlers.

    Parameters
    ----------
    app:
        The application instance.
    """
    for handler in app.on_shutdown:
        await _consume_result(_call_handler(app, handler, on_startup=False))

async def serve_lifespan(app, scope, receive, send) -> None:
    """Serve the ASGI lifespan protocol.

    Parameters
    ----------
    app:
        The application instance.
    scope, receive, send:
        The ASGI connection parameters.
    """
    first = True
    app_scope = scope
    await receive()
    try:
        if inspect.isasyncgenfunction(app.lifespan_context):
            async for item in app.lifespan_context(app_scope):
                assert first, "Lifespan context yielded multiple times."
                first = False
                await send({"type": "lifespan.startup.complete"})
                await receive()
        else:
            for item in app.lifespan_context(app_scope):
                assert first, "Lifespan context yielded multiple times."
                first = False
                await send({"type": "lifespan.startup.complete"})
                await receive()
    except BaseException:
        if first:
            exc_text = traceback.format_exc()
            await send({"type": "lifespan.startup.failed", "message": exc_text})
        if app.env == "local":
            raise
    else:
        await send({"type": "lifespan.shutdown.complete"})
