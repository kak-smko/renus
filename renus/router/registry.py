from __future__ import annotations

from renus.router.path import is_safe_path

_SUPPORTED_METHODS = ("GET", "POST", "PUT", "DELETE", "OPTIONS", "WS", "HEAD")

RouteEntry = dict

RouteResult = dict

def _build_result(route: RouteEntry, args: dict[str, object]) -> RouteResult:
    return {
        "path": route["path"],
        "args": args,
        "controller": route["controller"],
        "func": route["func"],
        "middlewares": route["middlewares"],
        "cache": route.get("cache", None),
    }

class RouteRegistry:
    """Instance-owned registry that stores and resolves registered routes."""

    def __init__(self) -> None:
        self._routes: dict[str, dict[str, list[RouteEntry]]] = {}
        self._subdomains_cache: list[str] | None = None
        self._matcher_cache: dict | None = None
        self._has_subdomains = False

    def register(self, subdomain: str, method: str, route_entry: RouteEntry) -> None:
        """Register a route entry for a subdomain and HTTP method."""
        sub = subdomain or "_"
        if sub not in self._routes:
            self._routes[sub] = {}
        if method not in self._routes[sub]:
            self._routes[sub][method] = []
        self._routes[sub][method].append(route_entry)
        if sub != "_":
            self._has_subdomains = True
        self._subdomains_cache = None
        self._matcher_cache = None

    def _matcher(self) -> dict:
        matcher = self._matcher_cache
        if matcher is None:
            matcher = {}
            has_subdomains = False
            for sub, methods in self._routes.items():
                if sub != "_":
                    has_subdomains = True
                buckets: dict = {}
                for method, routes in methods.items():
                    static: dict = {}
                    regexes: list = []
                    for entry in routes:
                        regex, params = entry["regex"]
                        if params:
                            regexes.append((regex, params, entry))
                        else:
                            static[entry["path"]] = entry
                    buckets[method] = (static, regexes)
                matcher[sub] = buckets
            self._has_subdomains = has_subdomains
            self._matcher_cache = matcher
        return matcher

    @property
    def has_subdomains(self) -> bool:
        """Whether any registered route requires request host inspection."""
        return self._has_subdomains
        
    def resolve_fast(self, scope) -> tuple[RouteEntry, dict[str, object]] | None:
        """Resolve a common HTTP request without constructing a ``Request``.

        This internal path is limited to the default subdomain and returns the
        registered route entry directly. The normal ``resolve`` method remains
        the compatibility path for callers that need subdomain handling or a
        route-result mapping.
        """
        method = scope.get("method")
        if method not in _SUPPORTED_METHODS:
            return None
        path = scope.get("path", "/")
        if path != "/":
            path = path.rstrip("/")
        if not is_safe_path(path):
            raise RuntimeError("Invalid path: path traversal detected")

        buckets = self._matcher().get("_")
        if buckets is None:
            return None
        static, regexes = buckets.get(method, (None, None))
        if static is not None:
            entry = static.get(path)
            if entry is not None:
                return entry, {}
        for regex, params, entry in regexes or ():
            match = regex.fullmatch(path)
            if match:
                return entry, {
                    name: convertor.convert(match.group(name))
                    for name, convertor in params.items()
                }
        return None

    def resolve(self, request, scope) -> RouteResult | None:
        """Resolve a request to a matching route result, or ``None``."""

        method = scope.get("method")
        if method is None:
            method = request.method
        if method not in _SUPPORTED_METHODS:
            return None

        path = scope.get("path", "/")
        if path != "/":
            path = path.rstrip("/")

        if not is_safe_path(path):
            raise RuntimeError("Invalid path: path traversal detected")

        routes = self._matcher()
        if self._has_subdomains:
            buckets = routes.get(getattr(request, "subdomain", "_"))
            if buckets is None:
                buckets = routes.get("_")
        else:
            buckets = routes.get("_")

        if buckets is None:
            return None
        spec = buckets.get(method)
        if spec is None:
            return None
        static, regexes = spec
        entry = static.get(path)
        if entry is not None:
            return _build_result(entry, {})
        for regex, params, route in regexes:
            match = regex.fullmatch(path)
            if match:
                args = {
                    name: convertor.convert(match.group(name))
                    for name, convertor in params.items()
                }
                return _build_result(route, args)

        return None

    @property
    def all(self) -> dict:
        """All registered routes grouped by subdomain and method."""
        return self._routes

    @property
    def subdomains(self) -> list:
        """The list of registered subdomains."""
        if self._subdomains_cache is None:
            self._subdomains_cache = list(self._routes.keys())
        return self._subdomains_cache

    def summary(self) -> str:
        """Return a human-readable summary of registered routes."""
        lines = []
        total = 0
        for sub, methods in sorted(self._routes.items()):
            for method, routes in sorted(methods.items()):
                for route in routes:
                    lines.append(
                        f"  {method:7s} {route['path']:40s} → {route.get('func', '?')}"
                    )
                    total += 1
        header = f"╔══ Route Registry: {total} routes registered ══╗"
        return header + "\n" + "\n".join(lines)

    def clear(self) -> None:
        """Clear all registered routes and caches."""
        self._routes.clear()
        self._subdomains_cache = None
        self._matcher_cache = None
        self._has_subdomains = False

