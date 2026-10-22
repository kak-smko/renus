from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ClassVar, Protocol, Self, TypeVar

from renus.db.core import convert


RowT_co = TypeVar("RowT_co", covariant=True)


class CompiledQuery(Protocol[RowT_co]):
    """Protocol describing a compiled query ready for execution."""

    pass


class CompiledMutation(Protocol):
    """Protocol describing a compiled mutation ready for execution."""

    pass


class QueryResult(Protocol[RowT_co]):
    """Protocol for an iterable set of returned rows."""

    def __iter__(self) -> Iterator[RowT_co]: ...


@dataclass(frozen=True, slots=True)
class MutationResult:
    """Result of a mutation: affected rows and generated data."""

    rows_affected: int
    last_id: Any = None
    generated: dict[str, Any] | None = None


class TransactionContext(Protocol):
    """Protocol for an active transactional context."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool: ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...

    async def rollback(self) -> None:
        """Roll back the transaction."""
        ...


class AsyncDatabaseAdapter(ABC):
    """Abstract async database adapter interface."""

    name: ClassVar[str]

    @abstractmethod
    async def connect(self) -> None:
        """Open the underlying database connection."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the underlying database connection."""
        pass

    @abstractmethod
    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        """Execute a compiled query and return the resulting rows."""
        pass

    @abstractmethod
    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        """Execute a compiled mutation and return its result."""
        pass

    @abstractmethod
    def transaction_factory(self) -> AsyncIterator[TransactionContext]:
        """Return an async iterator yielding new transaction contexts."""
        pass

    def _in_active_transaction(self) -> bool:
        return getattr(self, "_tx_session", None) is not None

    @abstractmethod
    async def health_check(self) -> bool:
        """Return whether the connection is healthy."""
        pass

    @abstractmethod
    async def create_schema(self, models: Any) -> None:
        """Create the database schema for the given models."""
        pass

    @abstractmethod
    async def ensure_migration_schema(
        self,
        table_name: str = "_db_migrations",
    ) -> None:
        """Ensure the migrations tracking table exists."""
        pass

    @abstractmethod
    async def get_applied_migrations(
        self,
        table_name: str = "_db_migrations",
    ) -> list[dict[str, Any]]:
        """Return the list of applied migrations."""
        pass

    @abstractmethod
    async def record_migration(
        self,
        version: str,
        name: str,
        checksum: str,
        applied_at: str,
        table_name: str = "_db_migrations",
    ) -> None:
        """Record an applied migration in the tracking table."""
        pass

    @abstractmethod
    async def remove_migration(
        self,
        version: str,
        table_name: str = "_db_migrations",
    ) -> None:
        """Remove a migration record from the tracking table."""
        pass

    @abstractmethod
    async def create_table(
        self,
        name: str,
        columns: Any,
        if_not_exists: bool = True,
    ) -> None:
        """Create a table from the given column definitions."""
        pass

    @abstractmethod
    async def drop_table(
        self,
        name: str,
        if_exists: bool = True,
    ) -> None:
        """Drop a table if it exists."""
        pass

    @abstractmethod
    async def add_column(
        self,
        table: str,
        column: Any,
    ) -> None:
        """Add a column to a table."""
        pass

    @abstractmethod
    async def drop_column(
        self,
        table: str,
        column_name: str,
    ) -> None:
        """Drop a column from a table."""
        pass

    @abstractmethod
    async def rename_column(
        self,
        table: str,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename a column in a table."""
        pass

    @abstractmethod
    async def rename_table(
        self,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename an existing table."""
        pass

    @abstractmethod
    async def create_index(
        self,
        table: str,
        fields: tuple[str, ...] | list[str],
        unique: bool = False,
        name: str | None = None,
    ) -> None:
        """Create an index on the given fields of a table."""
        pass

    @abstractmethod
    async def drop_index(
        self,
        table: str,
        name: str,
    ) -> None:
        """Drop an index from a table."""
        pass

    @abstractmethod
    async def tables(self) -> list[str]:
        """List the names of all tables in the database."""
        pass

    @abstractmethod
    async def backup(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        page_size: int | None = None,
    ) -> dict[str, int]:
        """Back up the database to the given path."""
        pass

    @abstractmethod
    async def restore(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        drop_existing: bool = True,
        chunk_size: int | None = None,
    ) -> dict[str, int]:
        """Restore the database from a backup at the given path."""
        pass

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={getattr(self, 'name', '?')!r}>"
