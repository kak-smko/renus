from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any, ClassVar, Self
from uuid import UUID

from renus.db.core.adapter import (
    CompiledMutation,
    CompiledQuery,
    MutationResult,
    QueryResult,
    TransactionContext,
)
from renus.db.core.capabilities import DatabaseCapabilities
from renus.db.core.exceptions import (
    ConfigurationError,
    ConnectionError,
    DatabaseError,
    DuplicateKeyError,
    IntegrityError,
)
from renus.db.mutation.ast import MutationAST
from renus.db.query.ast import QueryAST
from renus.db.sql.adapter import SQLAdapter
from renus.db.sql.compiler.compiler import SQLCompiled, SQLCompiler
from renus.db.sqlite.dialect import SQLiteDialect
from renus.db.sql.mutation import SQLMutationCompiler

__all__ = ["SQLiteAdapter", "SQLiteTransactionContext"]

DEFAULT_SQLITE_TIMEOUT = 5.0
DEFAULT_SQLITE_BUSY_TIMEOUT = 5000
CONNECT_RETRIES = 3
CONNECT_RETRY_DELAY = 0.5

class SQLiteTransactionContext:
    """Async context manager wrapping a SQLite connection transaction."""

    def __init__(self, conn: sqlite3.Connection, lock: asyncio.Lock) -> None:
        """Wrap a SQLite connection for transactional use.

        Parameters
        ----------
        conn:
            The connection participating in the transaction.
        lock:
            Asyncio lock serializing access to the connection.
        """
        self._conn = conn
        self._lock = lock
        self._active = False

    async def __aenter__(self) -> Self:
        async with self._lock:
            await asyncio.to_thread(self._conn.execute, "BEGIN;")
            self._active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if self._active:
            if exc is not None:
                await self.rollback()
            else:
                await self.commit()
        return False

    async def commit(self) -> None:
        """Commit the active transaction."""
        if self._active:
            async with self._lock:
                await asyncio.to_thread(self._conn.commit)
                self._active = False

    async def rollback(self) -> None:
        """Abort the active transaction."""
        if self._active:
            async with self._lock:
                await asyncio.to_thread(self._conn.rollback)
                self._active = False

class SQLiteAdapter(SQLAdapter):

    name: ClassVar[str] = "sqlite"

    capabilities: DatabaseCapabilities = DatabaseCapabilities(
        transactions=True,
        nested_documents=False,
        joins=True,
        foreign_keys=True,
        upsert=True,
        returning=True,
        json=True,
        arrays=False,
        cursor_pagination=True,
        bulk_operations=True,
        indexes=True,
        constraints=True,
    )

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the SQLite adapter.

        Parameters
        ----------
        config:
            Optional connection configuration dictionary. Defaults to empty.
        """
        self.config = config if config else {}
        self.dialect = SQLiteDialect()
        self.compiler = SQLCompiler(self.dialect)
        self.mutation_compiler = SQLMutationCompiler(self.dialect)
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._tx_session: Any = None

    def _normalize_param(self, p: Any) -> Any:
        if isinstance(p, datetime):
            return p.isoformat()
        if isinstance(p, date):
            return p.isoformat()
        if isinstance(p, UUID):
            return str(p)
        if isinstance(p, Decimal):
            return str(p)
        if isinstance(p, (dict, list)):
            return json.dumps(p)
        return p

    async def connect(self) -> None:
        """Establish a connection to the database."""
        if self._conn is not None:
            return

        cfg = self.config
        db_path = str(cfg.get("database", cfg.get("uri", ":memory:")))
        settings = cfg

        retries = max(1, int(settings.get("retries", CONNECT_RETRIES)))
        retry_delay = float(settings.get("retry_delay", CONNECT_RETRY_DELAY))
        timeout = float(settings.get("timeout", DEFAULT_SQLITE_TIMEOUT))
        busy_timeout = int(settings.get("busy_timeout", DEFAULT_SQLITE_BUSY_TIMEOUT))
        journal_mode = settings.get("journal_mode")
        if journal_mode is not None:
            journal_mode = str(journal_mode).strip().upper()
        in_memory = db_path in (":memory:", "")
        last_err: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                self._conn = await asyncio.to_thread(
                    sqlite3.connect,
                    database=db_path,
                    check_same_thread=False,
                    timeout=timeout,
                )
                self._conn.row_factory = sqlite3.Row
                await asyncio.to_thread(
                    self._conn.execute, f"PRAGMA busy_timeout = {busy_timeout};"
                )
                await asyncio.to_thread(self._conn.execute, "PRAGMA foreign_keys = ON;")
                if journal_mode is not None:
                    await asyncio.to_thread(
                        self._conn.execute, f"PRAGMA journal_mode = {journal_mode};"
                    )
                elif not in_memory:

                    await asyncio.to_thread(self._conn.execute, "PRAGMA journal_mode = WAL;")
                    await asyncio.to_thread(self._conn.execute, "PRAGMA synchronous = NORMAL;")

                last_err = None
                return
            except Exception as e:
                last_err = e
                if self._conn is not None:
                    try:
                        await asyncio.to_thread(self._conn.close)
                    except Exception:
                        pass
                    self._conn = None
                if attempt < retries:
                    await asyncio.sleep(retry_delay * (2 ** (attempt - 1)))

        raise ConnectionError(
            f"Failed to connect to SQLite at '{db_path}': {last_err}"
        ) from last_err

    async def disconnect(self) -> None:
        """Close the active database connection."""
        if self._conn is not None:
            conn = self._conn
            self._conn = None
            await asyncio.to_thread(conn.close)

    async def health_check(self) -> bool:
        """Return whether the database is reachable."""
        if self._conn is None:
            return False
        try:
            async with self._lock:
                await asyncio.to_thread(self._conn.execute, "SELECT 1;")
            return True
        except Exception:
            return False

    def transaction_factory(self) -> AsyncIterator[TransactionContext]:
        """Yield a SQLite transaction context for the caller."""
        if self._conn is None:
            raise ConfigurationError("Cannot create transaction context: SQLite is not connected")

        conn = self._conn
        adapter_self = self

        async def _tx_generator() -> AsyncIterator[TransactionContext]:
            ctx = SQLiteTransactionContext(conn, adapter_self._lock)
            adapter_self._tx_session = True
            try:
                yield ctx
            finally:
                adapter_self._tx_session = None

        return _tx_generator()

    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        """Execute a compiled query and return the results."""
        if self._conn is None:
            await self.connect()
        assert self._conn is not None

        if isinstance(compiled, QueryAST):
            sql_compiled: SQLCompiled = self.compile_query(compiled)
        else:
            sql_compiled = compiled

        params = tuple(self._normalize_param(p) for p in sql_compiled.params)
        try:
            async with self._lock:
                cursor = await asyncio.to_thread(
                    self._conn.execute,
                    sql_compiled.sql,
                    params,
                )
                rows = await asyncio.to_thread(cursor.fetchall)
            return [dict(r) for r in rows]
        except sqlite3.DatabaseError as e:
            raise DatabaseError(f"SQLite query execution error: {e}") from e

    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        """Execute a compiled mutation and return the result."""
        if self._conn is None:
            await self.connect()
        assert self._conn is not None

        if isinstance(compiled, MutationAST):
            sql_compiled: SQLCompiled = self.compile_mutation(compiled)
        else:
            sql_compiled = compiled

        params = tuple(self._normalize_param(p) for p in sql_compiled.params)
        try:
            async with self._lock:
                cursor = await asyncio.to_thread(
                    self._conn.execute,
                    sql_compiled.sql,
                    params,
                )
                if not self._in_active_transaction():
                    await asyncio.to_thread(self._conn.commit)

            rows_affected = cursor.rowcount if cursor.rowcount >= 0 else 1
            last_id = cursor.lastrowid if cursor.lastrowid else None
            return MutationResult(rows_affected=rows_affected, last_id=last_id)
        except sqlite3.IntegrityError as e:
            err_msg = str(e)
            if "UNIQUE" in err_msg or "PRIMARY" in err_msg:
                raise DuplicateKeyError(f"SQLite integrity error: {e}") from e
            raise IntegrityError(f"SQLite integrity error: {e}") from e
        except sqlite3.DatabaseError as e:
            raise DatabaseError(f"SQLite mutation error: {e}") from e

    async def raw_sql(
        self,
        sql: str,
        params: Any = (),
    ) -> list[dict[str, Any]]:
        """Execute raw SQL and return the resulting rows."""
        if self._conn is None:
            await self.connect()
        assert self._conn is not None

        p_list = params if isinstance(params, (list, tuple)) else (params,)
        normalized_params = tuple(self._normalize_param(p) for p in p_list)
        try:
            async with self._lock:
                cursor = await asyncio.to_thread(
                    self._conn.execute,
                    sql,
                    normalized_params,
                )
                rows = await asyncio.to_thread(cursor.fetchall)
            return [dict(r) for r in rows]
        except sqlite3.DatabaseError as e:
            raise DatabaseError(f"SQLite raw query error: {e}") from e

    async def execute_raw_sql(
        self,
        sql: str,
        params: Any = (),
    ) -> MutationResult:
        """Execute raw SQL and return the mutation result."""
        if self._conn is None:
            await self.connect()
        assert self._conn is not None

        p_list = params if isinstance(params, (list, tuple)) else (params,)
        normalized_params = tuple(self._normalize_param(p) for p in p_list)
        try:
            async with self._lock:
                cursor = await asyncio.to_thread(
                    self._conn.execute,
                    sql,
                    normalized_params,
                )
                if not self._in_active_transaction():
                    await asyncio.to_thread(self._conn.commit)

            rows_affected = cursor.rowcount if cursor.rowcount >= 0 else 1
            last_id = cursor.lastrowid if cursor.lastrowid else None
            return MutationResult(rows_affected=rows_affected, last_id=last_id)
        except sqlite3.IntegrityError as e:
            err_msg = str(e)
            if "UNIQUE" in err_msg or "PRIMARY" in err_msg:
                raise DuplicateKeyError(f"SQLite integrity error: {e}") from e
            raise IntegrityError(f"SQLite integrity error: {e}") from e
        except sqlite3.DatabaseError as e:
            raise DatabaseError(f"SQLite mutation error: {e}") from e

    async def _open_schema_session(self) -> Any:
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        return self._conn

    async def _execute_ddl(self, sql: str) -> None:
        assert self._conn is not None
        async with self._lock:
            await asyncio.to_thread(self._conn.execute, sql)

    async def _commit_schema(self) -> None:
        assert self._conn is not None
        async with self._lock:
            await asyncio.to_thread(self._conn.commit)

    async def _close_schema_session(self) -> None:
        return None
