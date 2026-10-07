from __future__ import annotations

from collections.abc import Callable, Iterator

from renus.router.convertors import build_path
from renus.router.path import full_path_builder
from renus.router.registry import RouteEntry

Controller = Callable | None


class Router:
    """Declarative API for defining and composing routes."""

    def __init__(
        self,
        prefix: str = "",
        middlewares: list[Callable] | None = None,
        subdomain: str | None = None,
    ) -> None:
        """Create a router whose routes can be mounted on another router or app."""
        if subdomain == "_":
            raise ValueError("subdomain cannot be '_'")

        self._prefix = prefix
        self._middlewares = list(middlewares or [])
        self._subdomain = subdomain or "_"
        self._routes: list[tuple[str, RouteEntry]] = []
        self._included: list[tuple[Router, str, list[Callable]]] = []

    def __enter__(self) -> "Router":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    def _add(
        self,
        path: str,
        controller: Controller,
        func,
        method: str,
        middlewares: list[Callable] | None = None,
        cache: int | None = None,
    ) -> RouteEntry:
        entry: RouteEntry = {
            "path": full_path_builder("", path),
            "controller": controller,
            "func": func,
            "middlewares": list(middlewares or []),
            "regex": None,
        }
        if cache:
            entry["cache"] = cache
        self._routes.append((method, entry))
        return entry

    def _iter_routes(
        self,
        prefix: str = "",
        middlewares: list[Callable] | None = None,
        subdomain: str = "_",
    ) -> Iterator[tuple[str, str, RouteEntry]]:
        """Yield routes after applying all inherited prefixes and middleware."""
        full_prefix = full_path_builder(prefix, self._prefix)
        full_middlewares = list(middlewares or []) + self._middlewares
        full_subdomain = self._subdomain if self._subdomain != "_" else subdomain

        for method, route in self._routes:
            path = full_path_builder(full_prefix, route["path"])
            entry = {
                **route,
                "path": path,
                "middlewares": full_middlewares + route["middlewares"],
                "regex": build_path(path),
            }
            yield full_subdomain, method, entry

        for child, child_prefix, child_middlewares in self._included:
            yield from child._iter_routes(
                prefix=full_path_builder(full_prefix, child_prefix),
                middlewares=full_middlewares + child_middlewares,
                subdomain=full_subdomain,
            )

    def get(
        self,
        path: str,
        controller: Controller = None,
        func: Callable | str | None = None,
        middlewares: list[Callable] | None = None,
        cache: int | None = None,
    ) -> "Router":
        """Register a ``GET`` route and return the router."""
        self._add(path, controller, func, "GET", middlewares, cache)
        return self

    def head(
        self,
        path: str,
        controller: Controller = None,
        func: Callable | str | None = None,
        middlewares: list[Callable] | None = None,
        cache: int | None = None,
    ) -> "Router":
        """Register a ``HEAD`` route and return the router."""
        self._add(path, controller, func, "HEAD", middlewares, cache)
        return self

    def post(
        self,
        path: str,
        controller: Controller = None,
        func: Callable | str | None = None,
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        """Register a ``POST`` route and return the router."""
        self._add(path, controller, func, "POST", middlewares)
        return self

    def put(
        self,
        path: str,
        controller: Controller = None,
        func: Callable | str | None = None,
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        """Register a ``PUT`` route and return the router."""
        self._add(path, controller, func, "PUT", middlewares)
        return self

    def delete(
        self,
        path: str,
        controller: Controller = None,
        func: Callable | str | None = None,
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        """Register a ``DELETE`` route and return the router."""
        self._add(path, controller, func, "DELETE", middlewares)
        return self

    def option(
        self,
        path: str,
        controller: Controller = None,
        func: Callable | str | None = None,
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        """Register an ``OPTIONS`` route and return the router."""
        self._add(path, controller, func, "OPTIONS", middlewares)
        return self

    def ws(
        self,
        path: str,
        controller: Controller = None,
        func: Callable | str | None = None,
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        """Register a ``WS`` route and return the router."""
        self._add(path, controller, func, "WS", middlewares)
        return self

    def include(
        self,
        router: "Router",
        prefix: str = "",
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        """Include another router under an optional prefix and middleware set."""
        if not isinstance(router, Router):
            raise TypeError("router must be a Router instance")
        if router is self or router._contains(self):
            raise ValueError("Including this router would create a cycle")
        self._included.append((router, prefix, list(middlewares or [])))
        return self

    def _contains(self, target: "Router") -> bool:
        return any(child is target or child._contains(target) for child, _, _ in self._included)

    def group(
        self,
        prefix: str = "",
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        """Create and include a child router with an additional route context."""
        group = Router(prefix=prefix, middlewares=middlewares)
        self.include(group)
        return group

