from __future__ import annotations

from typing import Any, Self, TypeVar

from renus.config import Config
from renus.db.core.adapter import AsyncDatabaseAdapter
from renus.db.core.exceptions import ConfigurationError, UnsupportedOperationError
from renus.db.plugins.core import Plugin, PluginManager
from renus.db.repository.core import Repository
from renus.db.transaction.core import Transaction
from renus.db.unit_of_work.core import UnitOfWork

__all__ = ["Database"]

T = TypeVar("T")

class Database:
    """High-level facade over one or more database adapters."""

    def __init__(
        self,
        adapter: AsyncDatabaseAdapter | None = None,
        *,
        adapters: dict[str, AsyncDatabaseAdapter] | None = None,
    ) -> None:
        """Set up the connection registry and plugin manager.

        Parameters
        ----------
        adapter:
            Adapter used as the ``"primary"`` connection. Defaults to one
            resolved from the ``database`` config.
        adapters:
            Optional mapping of named connections to adapters. A ``"primary"``
            key overrides the resolved default.
        """
        self._adapters: dict[str, AsyncDatabaseAdapter] = {}
        self._config = Config("database")
        self._plugins = PluginManager(self)

        if adapter is not None:
            self._adapters["primary"] = adapter
        elif adapters and "primary" in adapters:
            pass
        else:
            self._adapters["primary"] = self._resolve_adapter_from_config("primary")

        if adapters:
            self._adapters.update(adapters)

    def _resolve_adapter_from_config(
        self,
        connection: str = "primary",
    ) -> AsyncDatabaseAdapter:

        raw = (
            self._config.get(f"{connection}.adapter")
            or self._config.get(f"connections.{connection}.adapter")
            or self._config.get("adapter")
            or self._config.get(f"{connection}.driver")
            or self._config.get(f"connections.{connection}.driver")
            or self._config.get("driver")
        )
        if raw is None:
            raise ConfigurationError(
                f"No adapter configured for connection '{connection}' in Config('database')"
            )

        if isinstance(raw, AsyncDatabaseAdapter):
            return raw

        if callable(raw):
            res = raw()
            if isinstance(res, AsyncDatabaseAdapter):
                return res
            raise ConfigurationError(
                f"Adapter factory for connection '{connection}' returned invalid type {type(res).__name__}, expected AsyncDatabaseAdapter"
            )

        if isinstance(raw, str):
            driver_name = raw.strip().lower()
            from renus.db.plugins.registry import get_adapter
            try:
                factory = get_adapter(driver_name)
            except ConfigurationError:
                raise
            except Exception as exc:
                raise ConfigurationError(
                    f"Failed to load adapter '{driver_name}' for connection '{connection}': {exc}"
                ) from exc

            if callable(factory):
                res = factory()
                if isinstance(res, AsyncDatabaseAdapter):
                    return res
                raise ConfigurationError(
                    f"Adapter factory '{driver_name}' returned invalid type {type(res).__name__}, expected AsyncDatabaseAdapter"
                )
            if isinstance(factory, AsyncDatabaseAdapter):
                return factory
            raise ConfigurationError(
                f"Loaded adapter '{driver_name}' is not an AsyncDatabaseAdapter: {type(factory).__name__}"
            )

        raise ConfigurationError(
            f"Invalid adapter configured for connection '{connection}': {raw!r}. Expected AsyncDatabaseAdapter, callable factory, or driver name."
        )

    @property
    def config(self) -> Config:
        """Return the active database configuration."""
        return self._config

    @property
    def plugins(self) -> PluginManager:
        """Return the plugin manager for this database instance."""
        return self._plugins

    def use(self, plugin: Plugin | type[Plugin]) -> Database:
        """Register a plugin and return this database for chaining."""
        self._plugins.register(plugin)
        return self

    def register_adapter(
        self,
        name: str,
        adapter: AsyncDatabaseAdapter,
    ) -> None:
        """Register or replace an adapter for a named connection."""
        self._adapters[name] = adapter

    def adapter(self, name: str = "primary") -> AsyncDatabaseAdapter:
        """Return the adapter registered for a connection name."""
        if name not in self._adapters:
            raise ConfigurationError(
                f"No adapter registered for connection '{name}'. Available: {list(self._adapters.keys())}"
            )
        return self._adapters[name]

    def repository(
        self,
        model: type[T],
        connection: str = "primary",
    ) -> Repository[T]:
        """Create a repository for a model on a connection."""
        return Repository(self, model, connection)

    def unit_of_work(self, connection: str = "primary") -> UnitOfWork:
        """Start a unit of work on a connection."""
        return UnitOfWork(self.adapter(connection), connection)

    def transaction(self, connection: str = "primary") -> Transaction:
        """Create a transaction context for a connection."""
        return Transaction(self.adapter(connection))

    async def execute_raw(
        self,
        raw: Any,
        params: tuple[Any, ...] | list[Any] | None = None,
        connection: str = "primary",
    ) -> list[dict[str, Any]]:
        """Execute a raw query on a connection and return result rows."""
        adapter = self.adapter(connection)
        if hasattr(adapter, "execute_raw"):
            exec_fn = getattr(adapter, "execute_raw")
            return await exec_fn(raw, params)
        raise UnsupportedOperationError(
            f"Adapter '{type(adapter).__name__}' does not support execute_raw"
        )

    async def connect(self, connection: str | None = None) -> None:
        """Open one named connection, or all connections when none is given."""
        if connection is not None:
            await self.adapter(connection).connect()
            await self._plugins.dispatch_connect(connection)
        else:
            for name, adapt in self._adapters.items():
                await adapt.connect()
                await self._plugins.dispatch_connect(name)

    async def disconnect(self, connection: str | None = None) -> None:
        """Close one named connection, or all connections when none is given."""
        if connection is not None:
            await self.adapter(connection).disconnect()
            await self._plugins.dispatch_disconnect(connection)
        else:
            for name, adapt in self._adapters.items():
                await adapt.disconnect()
                await self._plugins.dispatch_disconnect(name)

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.disconnect()

    async def health_check(self, connection: str = "primary") -> bool:
        """Report whether a connection is healthy."""
        return await self.adapter(connection).health_check()

    async def create_schema(
        self,
        models: Any,
        connection: str = "primary",
    ) -> None:
        """Create the schema for the given models on a connection."""
        await self.adapter(connection).create_schema(models)

    def migration_manager(
        self,
        path: str = "migrations",
        connection: str = "primary",
    ) -> Any:
        """Create a migration manager bound to this database."""
        from renus.db.migrations.manager import MigrationManager

        return MigrationManager(self, path=path, connection=connection)

    async def tables(self, connection: str = "primary") -> list[str]:
        """Return the table names available on a connection."""
        adapter = self.adapter(connection)
        return await adapter.tables()

    async def backup(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        connection: str = "primary",
        page_size: int | None = None,
    ) -> dict[str, int]:
        """Back up the selected tables to a path and return row counts."""
        adapter = self.adapter(connection)
        return await adapter.backup(path=path, tables=tables, page_size=page_size)

    async def restore(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        drop_existing: bool = True,
        connection: str = "primary",
        chunk_size: int | None = None,
    ) -> dict[str, int]:
        """Restore tables from a backup path and return row counts."""
        adapter = self.adapter(connection)
        return await adapter.restore(
            path=path,
            tables=tables,
            drop_existing=drop_existing,
            chunk_size=chunk_size,
        )
