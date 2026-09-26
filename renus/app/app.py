import traceback

try:
    import uvicorn
except ImportError:
    uvicorn = None

from renus.config import Config
from renus.router import RouteRegistry, Router
from renus.router.convertors import build_path
from renus.router.path import full_path_builder

from .dispatch import serve_http, serve_websocket
from .handlers import build_endpoint, resolve_handler
from .lifespan import build_default_lifespan, serve_lifespan


class App:
    def __init__(
        self,
        lifespan=None,
        on_startup=None,
        on_shutdown=None,
    ) -> None:
        """Create a new application with an isolated route registry."""
        self.debug = Config("app").get("debug", False)
        self.env = Config("app").get("env", "local")
        self.on_startup = [] if on_startup is None else list(on_startup)
        self.on_shutdown = [] if on_shutdown is None else list(on_shutdown)
        self.registry = RouteRegistry()
        self.state = {}
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
        """Register a route for a given HTTP method."""
        return self._route_decorator(method.upper(), path, middlewares, cache)

    def get(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``GET`` route."""
        return self._route_decorator("GET", path, middlewares, cache)

    def post(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``POST`` route."""
        return self._route_decorator("POST", path, middlewares, cache)

    def put(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``PUT`` route."""
        return self._route_decorator("PUT", path, middlewares, cache)

    def delete(self, path: str, middlewares: list | None = None, cache: int | None = None):
        """Register a ``DELETE`` route."""
        return self._route_decorator("DELETE", path, middlewares, cache)

    def _route_decorator(self, method, path, middlewares=None, cache=None):
        def decorator(func):
            self._register_route(method, path, func, middlewares, cache)
            return func

        return decorator

    def _register_route(self, method, path, func, middlewares=None, cache=None):
        full_path = full_path_builder("", path)
        entry = {
            "path": full_path,
            "controller": None,
            "func": func,
            "middlewares": list(middlewares or []),
            "regex": build_path(full_path),
        }
        if cache:
            entry["cache"] = cache
        self.registry.register("_", method, entry)

    def include(
        self,
        router: Router,
        prefix: str = "",
        middlewares: list | None = None,
    ) -> "App":
        """Mount a router's routes into this application."""
        if not isinstance(router, Router):
            raise TypeError("router must be a Router instance")
        for subdomain, method, route in router._iter_routes(
            prefix=prefix,
            middlewares=middlewares,
        ):
            self.registry.register(subdomain, method, route)
        return self

    def run(
        self,
        app=None,
        host: str = "127.0.0.1",
        port: int = 8000,
        reload: bool = False,
        **options,
    ) -> None:
        """Run the server with uvicorn."""
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

        scope["app"] = self
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
