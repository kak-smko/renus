from __future__ import annotations

from types import TracebackType
from typing import Any, Self, TypeVar

from renus.db.core.adapter import AsyncDatabaseAdapter
from renus.db.core.exceptions import ConfigurationError
from renus.db.repository.core import Repository


T = TypeVar("T")

class UnitOfWork:
    """Coordinate repositories and transactional access to the database."""

    def __init__(
        self,
        adapter_or_database: AsyncDatabaseAdapter | Any,
        connection_name: str = "primary",
    ) -> None:
        """Build a unit of work around an adapter or database object.

        Parameters
        ----------
        adapter_or_database:
            The async database adapter, or an object exposing one.
        connection_name:
            Name of the connection to use. Defaults to ``"primary"``.
        """
        self.connection_name: str = connection_name
        self._repos: dict[type, Repository[Any]] = {}
        self._tx_context: Any = None
        self._tx_iter: Any = None
        self._committed: bool = False
        self._active: bool = False

        if isinstance(adapter_or_database, AsyncDatabaseAdapter):
            self._adapter: AsyncDatabaseAdapter = adapter_or_database
            self._db: Any = None
        else:
            self._db = adapter_or_database
            if hasattr(adapter_or_database, "adapter"):
                self._adapter = adapter_or_database.adapter(connection_name)
            elif hasattr(adapter_or_database, "_adapter"):
                self._adapter = adapter_or_database._adapter
            else:
                self._adapter = adapter_or_database

    @property
    def adapter(self) -> AsyncDatabaseAdapter:
        """Return the underlying async database adapter."""
        return self._adapter

    @property
    def is_active(self) -> bool:
        """Return whether the unit of work is currently open."""
        return self._active

    @property
    def is_committed(self) -> bool:
        """Return whether the unit of work has been committed."""
        return self._committed

    def repository(self, model: type[T]) -> Repository[T]:
        """Return a repository for the given model, creating it on first use."""
        if model not in self._repos:
            self._repos[model] = Repository(self.adapter, model, self.connection_name)
        return self._repos[model]

    def register_repository(self, model: type[T], repo: Repository[T]) -> None:
        """Register a pre-built repository for a model."""
        self._repos[model] = repo

    def __getattr__(self, name: str) -> Any:

        clean_name = name.lower()
        for model, repo in self._repos.items():
            mname = model.__name__.lower()
            if mname == clean_name or f"{mname}s" == clean_name:
                return repo
        raise AttributeError(f"UnitOfWork has no repository registered for '{name}'")

    async def commit(self) -> None:
        """Commit the current transaction."""
        if not self._active:
            raise ConfigurationError("Cannot commit an inactive Unit of Work")

        if self._tx_context is not None:
            await self._tx_context.commit()
        self._committed = True

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        if not self._active:
            raise ConfigurationError("Cannot rollback an inactive Unit of Work")

        if self._tx_context is not None:
            await self._tx_context.rollback()
        self._committed = False

    async def __aenter__(self) -> Self:
        self._active = True
        self._committed = False

        factory_result = self.adapter.transaction_factory()

        if hasattr(factory_result, "__anext__") or hasattr(factory_result, "__aiter__"):
            self._tx_iter = factory_result
            self._tx_context = await anext(self._tx_iter)
        else:
            self._tx_context = factory_result

        if self._tx_context is not None and hasattr(self._tx_context, "__aenter__"):
            await self._tx_context.__aenter__()

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        try:
            if exc_val is not None:

                if self._tx_context is not None and not self._committed:
                    await self._tx_context.rollback()
            else:

                if self._tx_context is not None and not self._committed:
                    await self._tx_context.rollback()

            if self._tx_context is not None and hasattr(self._tx_context, "__aexit__"):
                await self._tx_context.__aexit__(exc_type, exc_val, exc_tb)

            if self._tx_iter is not None and hasattr(self._tx_iter, "aclose"):
                await self._tx_iter.aclose()
        finally:
            self._active = False

        return False
