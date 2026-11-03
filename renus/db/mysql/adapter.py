from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from decimal import Decimal
from types import TracebackType
from typing import Any, ClassVar, Self

from renus.db.core.adapter import (
    AsyncDatabaseAdapter,
    CompiledMutation,
    CompiledQuery,
    MutationResult,
    QueryResult,
    TransactionContext,
)
from renus.db.core.exceptions import ConfigurationError, ConnectionError
from renus.db import errors
from renus.db.mutation.ast import InsertMany, MutationAST
from renus.db.query.ast import QueryAST
from renus.db.sql.adapter import SQLAdapter
from renus.db.sql.compiler.compiler import SQLCompiled, SQLCompiler
from renus.db.mysql.dialect import MySQLDialect
from renus.db.sql.mutation import SQLMutationCompiler

try:
    import aiomysql
except ImportError:
    aiomysql = None


DEFAULT_MYSQL_MIN_POOL = 5
DEFAULT_MYSQL_MAX_POOL = 100
DEFAULT_MYSQL_CONNECT_TIMEOUT = 5
CONNECT_RETRIES = 3
CONNECT_RETRY_DELAY = 0.5

class MySQLTransactionContext(TransactionContext):
    """Async context manager wrapping a MySQL connection transaction."""

    def __init__(self, conn: Any, pool: Any) -> None:
        """Wrap a MySQL connection for transactional use.

        Parameters
        ----------
        conn:
            The acquired database connection participating in the transaction.
        pool:
            The connection pool the connection is released back to.
        """
        self._conn = conn
        self._pool = pool
        self._active = False

    async def __aenter__(self) -> Self:
        await self._conn.begin()
        self._active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            if self._active:
                if exc is not None:
                    await self.rollback()
                else:
                    await self.commit()
        finally:
            if self._pool is not None and self._conn is not None:
                self._pool.release(self._conn)
                self._conn = None
        return False

    async def commit(self) -> None:
        """Commit the active transaction."""
        if self._active and self._conn is not None:
            await self._conn.commit()
            self._active = False

    async def rollback(self) -> None:
        """Abort the active transaction."""
        if self._active and self._conn is not None:
            await self._conn.rollback()
            self._active = False

class MySQLAdapter(SQLAdapter):

    name: ClassVar[str] = "mysql"
    need_locked_parent: ClassVar[bool] = True

    _index_if_not_exists: ClassVar[str] = ""

    _table_options: ClassVar[str] = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the MySQL adapter.

        Parameters
        ----------
        config:
            Optional connection configuration dictionary. Defaults to empty.
        """
        self.config = config if config else {}
        self.dialect = MySQLDialect()
        self.compiler = SQLCompiler(self.dialect)
        self.mutation_compiler = SQLMutationCompiler(self.dialect)
        self._mysql_db: Any = None
        self._initialize_transaction_state()
        self._schema_conn: Any = None
        self._lock = asyncio.Lock()

    async def _create_pool(self, params: dict[str, Any]) -> Any:
        minsize = int(params.get("minsize", DEFAULT_MYSQL_MIN_POOL))
        maxsize = int(params.get("maxsize", DEFAULT_MYSQL_MAX_POOL))
        connect_timeout = int(params.get("connect_timeout", DEFAULT_MYSQL_CONNECT_TIMEOUT))
        host = params["host"]
        port = int(params["port"])
        user = params["user"]
        password = params["password"]

        if aiomysql is None:
            raise ConnectionError("No MySQL async driver available. Install 'aiomysql'.")

        return await aiomysql.create_pool(
            host=host,
            port=port,
            user=user,
            password=password,
            db=params["db"],
            minsize=minsize,
            maxsize=maxsize,
            autocommit=False,
            connect_timeout=connect_timeout,
        )

    async def _verify_connection(self) -> bool:
        conn = await self._mysql_db.acquire()
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                await cur.fetchone()
            await conn.commit()
            return True
        except Exception:
            try:
                await conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._mysql_db.release(conn)

    async def connect(self,) -> None:
        """Establish a connection pool to the database."""
        if self._mysql_db is not None:
            return

        cfg =  self.config

        params: dict[str, Any] = {
            "host": str(cfg.get("host", "localhost")),
            "port": int(cfg.get("port", 3306)),
            "user": str(cfg.get("username", cfg.get("user", "root"))),
            "password": str(cfg.get("password", "")),
            "db": str(cfg.get("database", cfg.get("db", "db"))),
            "minsize": int(cfg.get("min_pool", cfg.get("minsize", DEFAULT_MYSQL_MIN_POOL))),
            "maxsize": int(cfg.get("max_pool", cfg.get("maxsize", DEFAULT_MYSQL_MAX_POOL))),
            "connect_timeout": int(
                cfg.get("connect_timeout", DEFAULT_MYSQL_CONNECT_TIMEOUT)
            ),
        }

        if aiomysql is None:
            raise ConnectionError("No MySQL async driver available. Install 'aiomysql'.")

        retries = max(1, int(cfg.get("retries", CONNECT_RETRIES)))
        retry_delay = float(cfg.get("retry_delay", CONNECT_RETRY_DELAY))
        last_err: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                pool = await self._create_pool(params)
                self._mysql_db = pool
                if await self._verify_connection():
                    return
                raise ConnectionError("MySQL connection verification failed")
            except Exception as e:
                last_err = e
                if self._mysql_db is not None:
                    try:
                        self._mysql_db.close()
                        await self._mysql_db.wait_closed()
                    except Exception:
                        pass
                    self._mysql_db = None
                if attempt < retries:
                    await asyncio.sleep(retry_delay * (2 ** (attempt - 1)))

        raise ConnectionError(f"Failed to connect to MySQL: {last_err}") from last_err

    async def disconnect(self) -> None:
        """Close the active connection pool."""
        if self._mysql_db is not None:
            pool = self._mysql_db
            self._mysql_db = None
            if hasattr(pool, "close"):
                pool.close()
            if hasattr(pool, "wait_closed"):
                await pool.wait_closed()

    async def health_check(self) -> bool:
        """Return whether the database is reachable."""
        if self._mysql_db is None:
            return False
        conn = None
        try:
            conn = await self._mysql_db.acquire()
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                await cur.fetchone()
            await conn.commit()
            return True
        except Exception:
            if conn is not None:
                try:
                    await conn.rollback()
                except Exception:
                    pass
            return False
        finally:
            if conn is not None and self._mysql_db is not None:
                self._mysql_db.release(conn)

    def transaction_factory(self) -> AsyncIterator[TransactionContext]:
        """Yield a MySQL transaction context for the caller."""
        if self._mysql_db is None:
            raise ConfigurationError("Cannot create transaction context: MySQL is not connected")

        pool = self._mysql_db
        adapter_self = self

        async def _tx_generator() -> AsyncIterator[TransactionContext]:
            if adapter_self._in_active_transaction():
                raise ConfigurationError("Nested transactions are not supported")
            conn = await pool.acquire()
            adapter_self._tx_session = conn
            ctx = MySQLTransactionContext(conn, pool)
            try:
                yield ctx
            finally:
                adapter_self._tx_session = None

        return _tx_generator()

    async def _reconnect_if_dropped(self) -> None:
        await self.disconnect()
        await self.connect()

    @staticmethod
    def _natural_sort_key(value: Any) -> tuple[tuple[int, Any], ...]:
        return tuple(
            (1, int(part)) if part.isdigit() else (0, part.casefold())
            for part in re.findall(r"[A-Za-z]+|\d+", str(value))
        )

    @classmethod
    def _sort_joined_collection(
        cls,
        value: Any,
        path: tuple[str, ...],
        primary_key: str,
    ) -> None:
        if not path:
            return
        if isinstance(value, list):
            for item in value:
                cls._sort_joined_collection(item, path, primary_key)
            return
        if not isinstance(value, dict):
            return
        if len(path) == 1:
            children = value.get(path[0])
            if isinstance(children, list):
                children.sort(
                    key=lambda child: cls._natural_sort_key(
                        child.get(primary_key, "") if isinstance(child, dict) else ""
                    )
                )
            return
        cls._sort_joined_collection(value.get(path[0]), path[1:], primary_key)

    def _decode_joined_rows(
        self,
        rows: list[Any],
        compiled: SQLCompiled,
    ) -> list[dict[str, Any]]:
        decoded = super()._decode_joined_rows(rows, compiled)
        for spec in compiled.joined:
            if not spec.get("collection"):
                continue
            target_meta = spec.get("meta")
            if target_meta is None:
                continue
            path = tuple(spec.get("path", ()))
            for row in decoded:
                self._sort_joined_collection(
                    row, path, target_meta.primary_key_field
                )
        return decoded

    async def _query_pool(
        self,
        sql_compiled: SQLCompiled,
        cursor_cls: Any,
    ) -> QueryResult[Any]:
        conn: Any = None
        try:
            conn = self._tx_session or await self._mysql_db.acquire()
            cursor_args = (cursor_cls,) if cursor_cls else ()
            async with conn.cursor(*cursor_args) as cur:
                await cur.execute(sql_compiled.sql, sql_compiled.params)
                rows = await cur.fetchall()
            if self._tx_session is None:
                await conn.commit()
            if getattr(sql_compiled, "joined", ()):
                return self._decode_joined_rows(list(rows), sql_compiled)
            meta = getattr(sql_compiled, "meta", None)
            if meta:
                return [self.dialect.decode_row(dict(r), meta) for r in rows]
            return [dict(r) if not isinstance(r, dict) else r for r in rows]
        except Exception as e:
            if conn is not None and self._tx_session is None:
                try:
                    await conn.rollback()
                except Exception:
                    pass
            raise errors.translate_driver_error("MySQL", "mysql", e, "query") from e
        finally:
            if conn is not None and self._tx_session is None and self._mysql_db is not None:
                self._mysql_db.release(conn)

    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        """Execute a compiled query and return the results."""
        if self._mysql_db is None:
            await self.connect()
        assert self._mysql_db is not None

        if isinstance(compiled, QueryAST):
            sql_compiled: SQLCompiled = self.compile_query(compiled)
            should_lock_rows = not compiled.aggregates and not compiled.group_by
        else:
            sql_compiled = compiled
            should_lock_rows = False

        if (
            self._in_active_transaction()
            and should_lock_rows
            and not sql_compiled.sql.rstrip().upper().endswith("FOR UPDATE")
        ):
            sql_compiled = SQLCompiled(
                f"{sql_compiled.sql} FOR UPDATE",
                sql_compiled.params,
                meta=sql_compiled.meta,
                joined=sql_compiled.joined,
                root_limit=sql_compiled.root_limit,
                root_offset=sql_compiled.root_offset,
            )

        cursor_cls = aiomysql.DictCursor if aiomysql is not None else None

        try:
            rows = await self._query_pool(sql_compiled, cursor_cls)
        except errors.DBConnectionError:
            if self._tx_session is not None:
                raise
            await self._reconnect_if_dropped()
            rows = await self._query_pool(sql_compiled, cursor_cls)

        if isinstance(compiled, QueryAST) and compiled.aggregates:
            aliases = {aggregate.alias for aggregate in compiled.aggregates}
            for row in rows:
                for alias in aliases:
                    value = row.get(alias)
                    if isinstance(value, Decimal):
                        row[alias] = float(value)
        return rows

    async def _mutation_pool(self, sql_compiled: SQLCompiled) -> MutationResult:
        conn: Any = None
        try:
            conn = self._tx_session or await self._mysql_db.acquire()
            async with conn.cursor() as cur:
                await cur.execute(sql_compiled.sql, sql_compiled.params)
                if self._tx_session is None:
                    await conn.commit()
                rows_affected = cur.rowcount if cur.rowcount >= 0 else 1
                last_id = cur.lastrowid if cur.lastrowid else None
                meta = getattr(sql_compiled, "meta", None)
                if meta and last_id is not None:
                    pk_meta = meta.fields.get(meta.primary_key_field) if meta.fields else None
                    if pk_meta is not None:
                        last_id = self.dialect.decode_value(last_id, pk_meta)
                return MutationResult(rows_affected=rows_affected, last_id=last_id)
        except Exception as e:
            if conn is not None and self._tx_session is None:
                try:
                    await conn.rollback()
                except Exception:
                    pass
            raise errors.translate_driver_error("MySQL", "mysql", e, "mutation") from e
        finally:
            if conn is not None and self._tx_session is None and self._mysql_db is not None:
                self._mysql_db.release(conn)

    def _with_insert_many_ids(
        self,
        mutation: CompiledMutation,
        result: MutationResult,
    ) -> MutationResult:
        if not isinstance(mutation, InsertMany) or result.last_id is None:
            return result

        meta = getattr(mutation.source, "__db_metadata__", None)
        if meta is None or not meta.identity.fields:
            return result
        pk_name = meta.primary_key_field
        pk_meta = meta.fields.get(pk_name)
        if pk_meta is None or not pk_meta.database.auto_inc:
            return result
        if any(record.get(pk_name) is not None for record in mutation.records):
            return result

        first_id = getattr(result.last_id, "value", result.last_id)
        ids = [
            self.dialect.decode_value(first_id + offset, pk_meta)
            for offset in range(len(mutation.records))
        ]
        generated = dict(result.generated or {})
        generated["ids"] = ids
        return MutationResult(
            rows_affected=result.rows_affected,
            last_id=result.last_id,
            generated=generated,
        )

    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        """Execute a compiled mutation and return the result."""
        if self._mysql_db is None:
            await self.connect()
        assert self._mysql_db is not None

        if isinstance(compiled, MutationAST):
            if self._needs_insert_many_shape_grouping(compiled):
                return await self._execute_insert_many_by_shape(compiled)
            sql_compiled: SQLCompiled = self.compile_mutation(compiled)
        else:
            sql_compiled = compiled

        try:
            result = await self._mutation_pool(sql_compiled)
        except errors.DBConnectionError:
            if self._tx_session is not None:
                raise
            await self._reconnect_if_dropped()
            result = await self._mutation_pool(sql_compiled)
        return self._with_insert_many_ids(compiled, result)

    async def _open_schema_session(self) -> Any:
        if self._mysql_db is None:
            await self.connect()
        assert self._mysql_db is not None
        self._schema_conn = await self._mysql_db.acquire()
        return self._schema_conn

    async def _execute_ddl(self, sql: str) -> None:
        assert self._schema_conn is not None
        async with self._schema_conn.cursor() as cur:
            await cur.execute(sql)

    async def _execute_index_ddl(self, sql: str) -> None:
        try:
            await self._execute_ddl(sql)
        except Exception:
            pass

    async def ensure_migration_schema(
        self,
        table_name: str = "_db_migrations",
    ) -> None:
        rows = await self.execute_query(
            SQLCompiled(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s LIMIT 1",
                (table_name,),
            )
        )
        if not rows:
            await super().ensure_migration_schema(table_name)

    async def _commit_schema(self) -> None:
        assert self._schema_conn is not None
        await self._schema_conn.commit()

    async def _close_schema_session(self) -> None:
        conn = self._schema_conn
        self._schema_conn = None
        if conn is not None and self._mysql_db is not None:
            self._mysql_db.release(conn)

    async def tables(self) -> list[str]:
        """Return the names of user tables."""
        excluded = {"_db_migrations"}
        sql = (
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name;"
        )
        rows = list(await self.execute_query(SQLCompiled(sql, ())))
        return [str(r["name"]) for r in rows if str(r["name"]) not in excluded]
