import inspect
import traceback

from renus.core.concurrency import run_in_threadpool
from renus.core.cache import Cache
from renus.core.status import Status
from renus.core.exception import debug_response
from renus.core.websockets import WebSocket
from renus.core.config import Config
from renus.core.routing import Router
from renus.core.request import Request
from renus.core.response import Response, TextResponse, JsonResponse
from renus.core.middleware import Middleware


class App:
    store = {}

    def __init__(self, routes:dict, lifespan=None,
                 on_startup=None,
                 on_shutdown=None, middlewares: list = None) -> None:
        self.routes = routes
        self.debug = Config('app').get('debug', False)
        self.env = Config('app').get('env', 'local')
        self.on_startup = [] if on_startup is None else list(on_startup)
        self.on_shutdown = [] if on_shutdown is None else list(on_shutdown)
        self.middlewares = [] if middlewares is None else middlewares

        async def default_lifespan(app):
            await self.startup()
            yield
            await self.shutdown()

        self.lifespan_context = default_lifespan if lifespan is None else lifespan

    async def __call__(self, scope, receive, send) -> None:
        assert scope["type"] in ("http", "websocket", "lifespan")

        if scope["type"] == "http":
            await self.http(scope, receive, send)

        if scope["type"] == "lifespan":
            await self.lifespan(scope, receive, send)

        if scope["type"] == "websocket":
            await self.websocket(scope, receive, send)

    async def lifespan(self, scope, receive, send) -> None:
        """
        Handle ASGI lifespan messages, which allows us to manage application
        startup and shutdown events.
        """
        first = True
        app = scope.get("app")
        await receive()
        try:
            if inspect.isasyncgenfunction(self.lifespan_context):
                async for item in self.lifespan_context(app):
                    assert first, "Lifespan context yielded multiple times."
                    first = False
                    await send({"type": "lifespan.startup.complete"})
                    await receive()
            else:
                for item in self.lifespan_context(app):  # type: ignore
                    assert first, "Lifespan context yielded multiple times."
                    first = False
                    await send({"type": "lifespan.startup.complete"})
                    await receive()
        except BaseException:
            if first:
                exc_text = traceback.format_exc()
                await send({"type": "lifespan.startup.failed", "message": exc_text})
            if self.env == 'local':
                raise
        else:
            await send({"type": "lifespan.shutdown.complete"})

    async def websocket(self, scope, receive, send) -> None:
        scope["method"] = 'WS'
        ws = WebSocket(scope, receive, send)

        try:
            res = self.load_routes(ws, scope)
            setattr(ws, 'route', res)
            if not res:
                await ws.close(1004)
            else:
                middlewares = self.middlewares + res['middlewares']
                passed = Middleware(ws, middlewares).next()

                if passed is not True:
                    await ws.close(1003)
                    return

                if res["controller"] is not None:
                    if 'request' in inspect.getfullargspec(res["controller"].__init__).args:
                        controller = res["controller"](ws)
                    else:
                        controller = res["controller"]()
                    method = getattr(controller, res['func'])
                else:
                    method = res['func']

                res['args']['ws'] = ws

                await method(**res['args'])

        except Exception as exc:
            debug_response(exc, self.debug)
            if self.env == 'local':
                raise

    async def http(self, scope, receive, send):
        scope["method"] = scope["method"].upper()
        request = Request(scope, receive)

        if scope["method"] in ['POST', 'PUT', 'DELETE']:
            setattr(request, 'inputs', await Request(scope, receive).form())

        try:
            await self.view(request, scope, receive, send)
        except Exception as exc:
            debug = debug_response(exc, self.debug)
            await self.result(request, JsonResponse(*debug), scope, receive, send)
            if self.env == 'local':
                raise

    async def view(self, request, scope, receive, send):
        res = self.load_routes(request, scope)
        setattr(request, 'route', res)

        if not res:
            await self.result(request, TextResponse('Path not Found', Status.HTTP_404_NOT_FOUND), scope, receive, send)
        else:
            middlewares = self.middlewares + res['middlewares']
            passed = Middleware(request, middlewares).next()

            if passed is not True and request.method != 'OPTIONS':
                await self.result(request, JsonResponse(passed, Status.HTTP_403_FORBIDDEN), scope, receive, send)
            else:
                if res["controller"] is not None:
                    if 'request' in inspect.getfullargspec(res["controller"].__init__).args:
                        controller = res["controller"](request)
                    else:
                        controller = res["controller"]()
                    method = getattr(controller, res['func'])
                else:
                    method = res['func']

                if 'request' in method.__code__.co_varnames:
                    res['args']['request'] = request

                r = await self.function(res, request, method)

                await self.result(request, r, scope, receive, send)

    async def function(self, res, request, method):
        async def get_async():
            if inspect.iscoroutinefunction(method):
                return await method(**res['args'])
            else:
                return await run_in_threadpool(method, **res['args'])

        if res['cache']:
            c = Cache(use_hash=True).get(request.full_path, None)

            if c is None:
                r = await get_async()
                Cache(use_hash=True).put(request.full_path, r, res['cache'])
            else:
                r = c
                r.raw_headers.append((b'r-cache', b'ok'))
        else:
            r = await get_async()
        return r

    async def startup(self) -> None:
        """
        Run any `.on_startup` event handlers.
        """
        print('application startup')
        for handler in self.on_startup:
            if inspect.isasyncgenfunction(handler):
                await handler()
            else:
                handler()

    async def shutdown(self) -> None:
        """
        Run any `.on_shutdown` event handlers.
        """
        print('application shutdown')
        for handler in self.on_shutdown:
            if inspect.isasyncgenfunction(handler):
                await handler()
            else:
                handler()

    async def result(self, request, response, scope, receive, send):
        if not isinstance(response, Response):
            response = TextResponse(response)
        await response(request, scope, receive, send)

    def load_routes(self, req, scope):
        return Router(scope, self.routes).response(req)
