from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from renus.db.core.adapter import AsyncDatabaseAdapter
from renus.db.core.exceptions import UnsupportedOperationError
from renus.db.database import Database
from renus.db.migrations.operations import Column
from renus.db.sql.compiler.compiler import SQLCompiled

__all__ = ["MigrationContext"]

class MigrationContext:
    """Provide migration DSL operations against a database adapter."""

    def __init__(
        self,
        db: Database,
        adapter: AsyncDatabaseAdapter | None = None,
        connection: str = "primary",
    ) -> None:
        """Bind a migration context to a database.

        Parameters
        ----------
        db:
            The database this context operates on.
        adapter:
            Optional adapter override; defaults to the database's adapter.
        connection:
            Connection name to use. Defaults to ``"primary"``.
        """
        self.db = db
        self.connection = connection
        self.adapter = adapter if adapter is not None else db.adapter(connection)

    async def create_table(
        self,
        name: str,
        columns: list[Column],
        if_not_exists: bool = True,
    ) -> None:
        """Create a table from column definitions."""
        await self.adapter.create_table(name, columns, if_not_exists=if_not_exists)

    async def drop_table(
        self,
        name: str,
        if_exists: bool = True,
    ) -> None:
        """Drop a table."""
        await self.adapter.drop_table(name, if_exists=if_exists)

    async def add_column(
        self,
        table: str,
        column: Column,
    ) -> None:
        """Add a column to a table."""
        await self.adapter.add_column(table, column)

    async def drop_column(
        self,
        table: str,
        column_name: str,
    ) -> None:
        """Remove a column from a table."""
        await self.adapter.drop_column(table, column_name)

    async def rename_column(
        self,
        table: str,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename a column in a table."""
        await self.adapter.rename_column(table, old_name, new_name)

    async def rename_table(
        self,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename a table."""
        await self.adapter.rename_table(old_name, new_name)

    async def create_index(
        self,
        table: str,
        fields: list[str] | tuple[str, ...],
        unique: bool = False,
        name: str | None = None,
    ) -> None:
        """Create an index on a table."""
        await self.adapter.create_index(table, fields, unique=unique, name=name)

    async def drop_index(
        self,
        table: str,
        name: str,
    ) -> None:
        """Drop an index from a table."""
        await self.adapter.drop_index(table, name)

    async def create_model_table(self, model: type[Any]) -> None:
        """Create the table for a single model."""
        await self.adapter.create_schema([model])

    async def create_model_schema(self, models: Iterable[type[Any]]) -> None:
        """Create schema for the given models."""
        await self.adapter.create_schema(models)

    async def execute_sql(
        self,
        sql: str,
        params: tuple[Any, ...] | list[Any] = (),
    ) -> Any:
        """Execute a raw SQL statement on the adapter."""
        if hasattr(self.adapter, "execute_raw_sql"):
            exec_fn = getattr(self.adapter, "execute_raw_sql")
            return await exec_fn(sql, params)
        if hasattr(self.adapter, "raw_sql"):
            exec_fn = getattr(self.adapter, "raw_sql")
            return await exec_fn(sql, params)
        if hasattr(self.adapter, "dialect"):
            p = tuple(params) if isinstance(params, (list, tuple)) else (params,)
            return await self.adapter.execute_mutation(SQLCompiled(sql, p))

        raise UnsupportedOperationError(
            f"Adapter '{type(self.adapter).__name__}' is not an SQL adapter"
        )

    async def execute_raw(
        self,
        raw: Any,
        params: tuple[Any, ...] | list[Any] | None = None,
    ) -> Any:
        """Execute raw SQL through the adapter's raw executor."""
        if hasattr(self.adapter, "execute_raw"):
            exec_fn = getattr(self.adapter, "execute_raw")
            return await exec_fn(raw, params)
        raise UnsupportedOperationError(
            f"Adapter '{type(self.adapter).__name__}' does not support execute_raw"
        )

    def __getattr__(self, item: str) -> Any:
        return getattr(self.db, item)
