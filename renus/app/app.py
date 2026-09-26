import traceback

try:
    import uvicorn
except ImportError:
    uvicorn = None

from renus.config import Config
from renus.router import Router

from .dispatch import serve_http, serve_websocket
from .handlers import build_endpoint, resolve_handler
from .lifespan import build_default_lifespan, serve_lifespan

class App:

    def __init__(
        self,
        lifespan=None,
        on_startup=None,
        on_shutdown=None,
        middlewares: list | None = None,
    ) -> None:
        """Create a new application.

        Parameters
        ----------
        lifespan:
            Optional custom ASGI lifespan context manager.
        on_startup:
            Optional callables to run on startup.
        on_shutdown:
            Optional callables to run on shutdown.
        middlewares:
            Optional list of ASGI middlewares to wrap the app.
        """
        self.debug = Config("app").get("debug", False)
        self.env = Config("app").get("env", "local")
        self.on_startup = [] if on_startup is None else list(on_startup)
        self.on_shutdown = [] if on_shutdown is None else list(on_shutdown)
        self.middlewares = [] if middlewares is None else middlewares
        self.router = Router()
        self.state={}

        self.lifespan_context = (
            build_default_lifespan(self) if lifespan is None else lifespan
        )

    def route(
        self,
        path: str,
        method: str = "GET",
        middlewares: list | None = None,
        cache: int | None = None,
    ):
        """Register a route for a given HTTP method.

        Parameters
        ----------
        path:
            URL path pattern to match.
        method:
            HTTP method. Defaults to ``"GET"``.
        middlewares:
            Optional list of middlewares for this route.
        cache:
            Optional cache TTL in seconds.
        """
        return self._route_decorator(method.upper(), path, middlewares, cache)

    def get(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``GET`` route.

        Parameters
        ----------
        path:
            URL path pattern to match.
        middlewares:
            Optional list of middlewares for this route.
        cache:
            Optional cache TTL in seconds.
        """
        return self._route_decorator("GET", path, middlewares, cache)

    def post(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``POST`` route.

        Parameters
        ----------
        path:
            URL path pattern to match.
        middlewares:
            Optional list of middlewares for this route.
        cache:
            Optional cache TTL in seconds.
        """
        return self._route_decorator("POST", path, middlewares, cache)

    def put(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``PUT`` route.

        Parameters
        ----------
        path:
            URL path pattern to match.
        middlewares:
            Optional list of middlewares for this route.
        cache:
            Optional cache TTL in seconds.
        """
        return self._route_decorator("PUT", path, middlewares, cache)

    def delete(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``DELETE`` route.

        Parameters
        ----------
        path:
            URL path pattern to match.
        middlewares:
            Optional list of middlewares for this route.
        cache:
            Optional cache TTL in seconds.
        """
        return self._route_decorator("DELETE", path, middlewares, cache)

    def _route_decorator(self, method, path, middlewares=None, cache=None):
        def decorator(func):
            self._register_route(method, path, func, middlewares, cache)
            return func

        return decorator

    def _register_route(self, method, path, func, middlewares=None, cache=None):
        fluent = {
            "GET": self.router.get,
            "POST": self.router.post,
            "PUT": self.router.put,
            "DELETE": self.router.delete,
            "HEAD": self.router.head,
            "OPTIONS": self.router.option,
            "WS": self.router.ws,
        }.get(method)
        if fluent is not None:
            if method in ("GET", "HEAD"):
                fluent(path, None, func, middlewares, cache)
            else:
                fluent(path, None, func, middlewares)
            return
        self.router._add(path, None, func, method, middlewares, cache)

    def run(
        self,
        app=None,
        host: str = "127.0.0.1",
        port: int = 8000,
        reload: bool = False,
        **options,
    ) -> None:
        """Run the server with uvicorn.

        Parameters
        ----------
        app:
            Optional ASGI app to run; defaults to this app.
        host:
            Host to bind. Defaults to ``"127.0.0.1"``.
        port:
            Port to bind. Defaults to ``8000``.
        reload:
            Enable auto-reload on code changes.
        options:
            Extra options passed to ``uvicorn.run``.
        """
        if uvicorn is None:
            traceback.print_exc()
            raise RuntimeError(
                "uvicorn is required to run the server. "
                "Install it with: pip install renus[server]"
            ) from None

        uvicorn.run(
            self if app is None else app,
            host=host,
            port=port,
            reload=reload,
            **options,
        )

    async def __call__(self, scope, receive, send) -> None:
        assert scope["type"] in ("http", "websocket", "lifespan")

        scope['app']=self
        if scope["type"] == "http":
            await serve_http(self, scope, receive, send)

        if scope["type"] == "lifespan":
            await serve_lifespan(self, scope, receive, send)

        if scope["type"] == "websocket":
            await serve_websocket(self, scope, receive, send)

    def _resolve_handler(self, res, request):
        return resolve_handler(res, request)

    def _endpoint(self, res, method, request):
        return build_endpoint(res, method, request)
