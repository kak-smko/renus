from __future__ import annotations

from collections.abc import Callable

from renus.router.convertors import build_path
from renus.router.path import full_path_builder
from renus.router.registry import RouteEntry, RouteRegistry

Controller = Callable | None

class Router:
    """Declarative API for registering routes and building sub-routers."""

    def __init__(
        self,
        prefix: str = "",
        middlewares: list[Callable] | None = None,
        subdomain: str | None = None,
    ) -> None:
        """Create a new router.

        Parameters
        ----------
        prefix:
            Optional path prefix applied to all routes.
        middlewares:
            Optional list of middlewares applied to all routes.
        subdomain:
            Optional subdomain these routes apply to.
        """
        if middlewares is None:
            middlewares = []

        if subdomain == "_":
            raise ValueError("subdomain cannot be '_'")

        self._prefix = prefix
        self._middlewares = middlewares
        self._subdomain = subdomain or "_"
        self._registry = RouteRegistry()

    def __enter__(self) -> "Router":
        """Return the router for use as a context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Return ``False`` to propagate exceptions unhandled."""
        return False

    def _add(
        self,
        path: str,
        controller: Controller,
        func,
        method: str,
        middlewares: list[Callable] | None = None,
        cache: int | None = None,
    ) -> None:
        if middlewares is None:
            middlewares = []

        full_path = full_path_builder(self._prefix, path)
        all_middlewares = self._middlewares.copy() + middlewares

        entry: RouteEntry = {
            "path": full_path,
            "controller": controller,
            "func": func,
            "middlewares": all_middlewares,
            "regex": build_path(full_path),
        }
        if cache:
            entry["cache"] = cache

        self._registry.register(self._subdomain, method, entry)

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

    def group(
        self,
        prefix: str = "",
        middlewares: list[Callable] | None = None,
    ) -> "Router":
        if middlewares is None:
            middlewares = []

        combined_prefix = full_path_builder(self._prefix, prefix)
        combined_middlewares = self._middlewares.copy() + middlewares

        """Return a new router inheriting this router's prefix and middlewares."""
        subdomain = None if self._subdomain == "_" else self._subdomain

        return Router(
            prefix=combined_prefix,
            middlewares=combined_middlewares,
            subdomain=subdomain,
        )

    def crud(
        self,
        path: str,
        controller: Controller = None,
        middlewares: list[Callable] | None = None,
        func_prefix: str = "",
    ) -> "Router":
        """Register index, store, update, and delete routes for a controller."""
        self._add(path, controller, f"{func_prefix}index", "GET", middlewares)
        self._add(path, controller, f"{func_prefix}store", "POST", middlewares)
        self._add(
            path + "/{id:id}", controller, f"{func_prefix}update", "PUT", middlewares
        )
        self._add(
            path + "/{id:id}",
            controller,
            f"{func_prefix}delete",
            "DELETE",
            middlewares,
        )
        return self

    def mcud(
        self,
        path: str,
        controller: Controller = None,
        middlewares: list[Callable] | None = None,
        func_prefix: str = "",
    ) -> "Router":
        """Register store, update, and delete routes for a controller."""
        self._add(path, controller, f"{func_prefix}m_store", "POST", middlewares)
        self._add(path, controller, f"{func_prefix}m_update", "PUT", middlewares)
        self._add(path, controller, f"{func_prefix}m_delete", "DELETE", middlewares)
        return self

__all__ = ["Router"]
