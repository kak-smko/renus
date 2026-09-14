from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterable
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
from renus.db.core.backup import (
    DEFAULT_PAGE_SIZE,
    BackupFileWriter,
    load_rows_pages,
)
from renus.db.core.exceptions import (
    ConfigurationError,
    ConnectionError,
)
from renus.db import errors
from renus.db.mongodb.compiler import MongoCompiledQuery, MongoCompiler
from renus.db.mutation.ast import MutationAST
from renus.db.query.ast import QueryAST

__all__ = ["MongoDBAdapter", "MongoTransactionContext"]

DEFAULT_MAX_POOL = 100
DEFAULT_MIN_POOL = 10
DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 30_000
DEFAULT_CONNECT_TIMEOUT_MS = 2_000
CONNECT_RETRIES = 3
CONNECT_RETRY_DELAY = 0.5
class MongoTransactionContext(TransactionContext):
    """Async context manager wrapping a MongoDB session transaction."""

    def __init__(self, session: Any) -> None:
        """Wrap a MongoDB session for transactional use.

        Parameters
        ----------
        session:
            The PyMongo session used to start and end transactions.
        """
        self._session = session
        self._active = False

    async def __aenter__(self) -> Self:

        await self._session.start_transaction()
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
            await self._session.end_session()
        return False

    async def commit(self) -> None:
        """Commit the active transaction."""
        if self._active:
            await self._session.commit_transaction()
            self._active = False

    async def rollback(self) -> None:
        """Abort the active transaction."""
        if self._active:
            await self._session.abort_transaction()
            self._active = False

class MongoDBAdapter(AsyncDatabaseAdapter):

    name: ClassVar[str] = "mongodb"

    nested_documents: ClassVar[bool] = True

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the MongoDB adapter.

        Parameters
        ----------
        config:
            Optional connection configuration dictionary. Defaults to empty.
        """
        self.config = config if config else {}
        self.compiler = MongoCompiler()
        self._mongo_client: Any = None
        self._mongo_db: Any = None
        self._tx_session: Any = None

    async def connect(self) -> None:
        """Establish a connection to the database."""
        if self._mongo_client is not None:
            return

        cfg = self.config

        uri = str(cfg.get("uri", "mongodb://localhost:27017"))
        db_name = str(cfg.get("database", "db"))

        client_kwargs: dict[str, Any] = {
            "maxPoolSize": int(cfg.get("max_pool", DEFAULT_MAX_POOL)),
            "minPoolSize": int(cfg.get("min_pool", DEFAULT_MIN_POOL)),
            "serverSelectionTimeoutMS": int(
                cfg.get("server_selection_timeout_ms", DEFAULT_SERVER_SELECTION_TIMEOUT_MS)
            ),
            "connectTimeoutMS": int(cfg.get("connect_timeout_ms", DEFAULT_CONNECT_TIMEOUT_MS)),
        }
        socket_timeout = cfg.get("socket_timeout_ms")
        if socket_timeout is not None:
            client_kwargs["socketTimeoutMS"] = int(socket_timeout)
        username = cfg.get("username")
        password = cfg.get("password")
        if username:
            client_kwargs["username"] = str(username)
        if password:
            client_kwargs["password"] = str(password)

        retries = max(1, int(cfg.get("retries", CONNECT_RETRIES)))
        delay = float(cfg.get("retry_delay", CONNECT_RETRY_DELAY))

        try:
            from pymongo import AsyncMongoClient
        except ImportError as exc:
            raise ConnectionError(
                "pymongo>=4.9 is required for native async MongoDB access. Install 'pymongo'."
            ) from exc

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._mongo_client = AsyncMongoClient(uri, **client_kwargs)
                self._mongo_db = self._mongo_client[db_name]
                await self._mongo_db.command("ping")
                return
            except Exception as e:
                last_err = e
                if self._mongo_client is not None:
                    close = getattr(self._mongo_client, "close", None)
                    if close is not None:
                        result = close()
                        if hasattr(result, "__await__"):
                            await result
                    self._mongo_client = None
                self._mongo_db = None
                if attempt < retries:
                    await asyncio.sleep(delay * (2 ** (attempt - 1)))

        raise ConnectionError(f"Failed to connect to MongoDB at '{uri}': {last_err}") from last_err

    async def disconnect(self) -> None:
        """Close the active database connection."""
        if self._mongo_client is not None:
            client = self._mongo_client
            self._mongo_client = None
            self._mongo_db = None
            close = getattr(client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    async def health_check(self) -> bool:
        """Return whether the database is reachable."""
        if self._mongo_db is None:
            return False
        try:
            await self._mongo_db.command("ping")
            return True
        except Exception:
            return False

    def transaction_factory(self) -> AsyncIterator[TransactionContext]:
        """Yield a MongoDB transaction context for the caller."""
        if self._mongo_client is None:
            raise ConfigurationError("Cannot create transaction context: MongoDB is not connected")

        client = self._mongo_client
        adapter_self = self

        async def _tx_generator() -> AsyncIterator[TransactionContext]:
            if adapter_self._in_active_transaction():
                raise ConfigurationError("Nested transactions are not supported")

            session = client.start_session()
            adapter_self._tx_session = session
            ctx = MongoTransactionContext(session)
            try:
                yield ctx
            finally:
                adapter_self._tx_session = None

        return _tx_generator()

    def compile_query(self, ast: QueryAST) -> MongoCompiledQuery:
        """Compile a query AST using the MongoDB compiler."""
        return self.compiler.compile_query(ast)

    def compile_mutation(self, ast: MutationAST) -> tuple[str, str, dict[str, Any], Any]:
        """Compile a mutation AST using the MongoDB compiler."""
        return self.compiler.compile_mutation(ast)

    async def _reconnect_if_dropped(self) -> None:
        await self.disconnect()
        await self.connect()

    async def _run_query(self, mongo_query: MongoCompiledQuery) -> QueryResult[Any]:
        assert self._mongo_db is not None
        coll = self._mongo_db[mongo_query.collection]
        session = self._tx_session
        try:
            if mongo_query.pipeline is not None:
                cursor = await coll.aggregate(mongo_query.pipeline, session=session)
                docs = await cursor.to_list(length=mongo_query.limit or 5000)
            else:

                cursor = coll.find(
                    mongo_query.filter,
                    projection=mongo_query.projection,
                    session=session,
                )
                if mongo_query.sort:
                    cursor = cursor.sort(mongo_query.sort)
                if mongo_query.skip is not None:
                    cursor = cursor.skip(mongo_query.skip)
                if mongo_query.limit is not None:
                    cursor = cursor.limit(mongo_query.limit)

                docs = await cursor.to_list(length=mongo_query.limit or 5000)

            results: list[dict[str, Any]] = []
            for d in docs:
                doc = dict(d)
                if "_id" in doc and "id" not in doc:
                    doc["id"] = doc["_id"]
                results.append(doc)

            return results
        except Exception as e:
            raise errors.translate_driver_error("MongoDB", "mongodb", e, "query") from e

    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        """Execute a compiled query and return the results."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None

        if isinstance(compiled, QueryAST):
            mongo_query = self.compile_query(compiled)
        elif isinstance(compiled, MongoCompiledQuery):
            mongo_query = compiled
        else:
            raise ValueError(f"Expected MongoCompiledQuery, got {type(compiled).__name__}")

        try:
            return await self._run_query(mongo_query)
        except errors.DBConnectionError:
            if self._tx_session is not None:
                raise
            await self._reconnect_if_dropped()
            return await self._run_query(mongo_query)

    async def _run_mutation(
        self,
        coll_name: str,
        op: str,
        filt_or_doc: Any,
        extra: Any,
    ) -> MutationResult:
        assert self._mongo_db is not None
        coll = self._mongo_db[coll_name]
        session = self._tx_session
        try:
            if op == "insert_one":
                res = await coll.insert_one(filt_or_doc, session=session)
                return MutationResult(rows_affected=1, last_id=res.inserted_id)

            if op == "insert_many":
                docs = filt_or_doc.get("docs", [])
                res = await coll.insert_many(docs, session=session)
                return MutationResult(
                    rows_affected=len(res.inserted_ids),
                    generated={"ids": res.inserted_ids},
                )

            if op == "update_one":
                res = await coll.update_one(filt_or_doc, extra, session=session)
                return MutationResult(rows_affected=res.modified_count)

            if op == "update_many":
                res = await coll.update_many(filt_or_doc, extra, session=session)
                return MutationResult(rows_affected=res.modified_count)

            if op == "delete_one":
                res = await coll.delete_one(filt_or_doc, session=session)
                return MutationResult(rows_affected=res.deleted_count)

            if op == "delete_many":
                res = await coll.delete_many(filt_or_doc, session=session)
                return MutationResult(rows_affected=res.deleted_count)

            if op == "upsert":
                res = await coll.update_one(filt_or_doc, extra, upsert=True, session=session)
                last_id = res.upserted_id if res.upserted_id is not None else None
                rows = 1 if (res.upserted_id is not None or res.modified_count > 0) else 0
                return MutationResult(rows_affected=rows, last_id=last_id)

            raise NotImplementedError(f"Unsupported MongoDB operation: {op}")
        except Exception as e:
            raise errors.translate_driver_error("MongoDB", "mongodb", e, "mutation") from e

    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        """Execute a compiled mutation and return the result."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None

        if isinstance(compiled, MutationAST):
            coll_name, op, filt_or_doc, extra = self.compile_mutation(compiled)
        elif isinstance(compiled, tuple) and len(compiled) == 4:
            coll_name, op, filt_or_doc, extra = compiled
        else:
            raise ValueError(f"Unsupported compiled mutation format: {type(compiled).__name__}")

        try:
            return await self._run_mutation(coll_name, op, filt_or_doc, extra)
        except errors.DBConnectionError:
            if self._tx_session is not None:
                raise
            await self._reconnect_if_dropped()
            return await self._run_mutation(coll_name, op, filt_or_doc, extra)

    async def create_schema(self, models: Iterable[Any]) -> None:
        """Create collections and indexes for the given models."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None

        for model in models:
            meta = getattr(model, "__db_metadata__", None)
            if not meta:
                continue

            coll = self._mongo_db[meta.table]

            for idx in meta.indexes:
                keys = [(f, 1) for f in idx.fields]
                try:
                    await coll.create_index(keys, unique=idx.unique)
                except Exception:
                    pass

    async def ensure_migration_schema(
        self,
        table_name: str = "_db_migrations",
    ) -> None:
        """Ensure the migrations collection and unique version index exist."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        coll = self._mongo_db[table_name]
        try:
            await coll.create_index([("version", 1)], unique=True)
        except Exception:
            pass

    async def get_applied_migrations(
        self,
        table_name: str = "_db_migrations",
    ) -> list[dict[str, Any]]:
        """Return all applied migrations sorted by version."""
        await self.ensure_migration_schema(table_name)
        assert self._mongo_db is not None
        coll = self._mongo_db[table_name]
        cursor = coll.find({}).sort("version", 1)
        docs = await cursor.to_list(length=5000)
        return [dict(d) for d in docs]

    async def record_migration(
        self,
        version: str,
        name: str,
        checksum: str,
        applied_at: str,
        table_name: str = "_db_migrations",
    ) -> None:
        """Record an applied migration in the migrations collection."""
        await self.ensure_migration_schema(table_name)
        assert self._mongo_db is not None
        coll = self._mongo_db[table_name]
        await coll.insert_one({
            "version": version,
            "name": name,
            "applied_at": applied_at,
            "checksum": checksum,
        })

    async def remove_migration(
        self,
        version: str,
        table_name: str = "_db_migrations",
    ) -> None:
        """Remove a migration record by version."""
        await self.ensure_migration_schema(table_name)
        assert self._mongo_db is not None
        coll = self._mongo_db[table_name]
        await coll.delete_one({"version": version})

    async def create_table(
        self,
        name: str,
        columns: Any,
        if_not_exists: bool = True,
    ) -> None:
        """Create a new collection in the database."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        try:
            await self._mongo_db.create_collection(name)
        except Exception:
            pass

    async def drop_table(
        self,
        name: str,
        if_exists: bool = True,
    ) -> None:
        """Drop a collection from the database."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        try:
            await self._mongo_db.drop_collection(name)
        except Exception:
            pass

    async def add_column(
        self,
        table: str,
        column: Any,
    ) -> None:
        """Add a column by setting its default on existing documents."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        name = getattr(column, "name", None)
        default = getattr(column, "default", None)
        if not name or default is None:
            return
        await self._mongo_db[table].update_many({}, {"$set": {name: default}})

    async def drop_column(
        self,
        table: str,
        column_name: str,
    ) -> None:
        """Remove a column from all documents in a collection."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        await self._mongo_db[table].update_many({}, {"$unset": {column_name: ""}})

    async def rename_column(
        self,
        table: str,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename a column across all documents in a collection."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        await self._mongo_db[table].update_many({}, {"$rename": {old_name: new_name}})

    async def rename_table(
        self,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename a collection in the database."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        await self._mongo_db[old_name].rename(new_name)

    async def create_index(
        self,
        table: str,
        fields: tuple[str, ...] | list[str],
        unique: bool = False,
        name: str | None = None,
    ) -> None:
        """Create an index on the given fields of a collection."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        keys = [(f, 1) for f in fields]
        idx_name = name or f"idx_{table}_{'_'.join(fields)}"
        await self._mongo_db[table].create_index(keys, unique=unique, name=idx_name)

    async def drop_index(
        self,
        table: str,
        name: str,
    ) -> None:
        """Drop an index from a collection by name."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        await self._mongo_db[table].drop_index(name)

    async def tables(self) -> list[str]:
        """Return the names of user collections."""
        if self._mongo_db is None:
            await self.connect()
        assert self._mongo_db is not None
        names = await self._mongo_db.list_collection_names()
        excluded = {"_db_migrations", "system.views"}
        return [name for name in names if name not in excluded]

    async def backup(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        page_size: int | None = None,
    ) -> dict[str, int]:
        """Back up collections to JSON files and return per-table counts."""
        page_size = page_size or DEFAULT_PAGE_SIZE
        target_tables = tables if tables is not None else await self.tables()
        os.makedirs(path, exist_ok=True)
        counts: dict[str, int] = {}

        assert self._mongo_db is not None
        for table in target_tables:
            file_path = os.path.join(path, f"{table}.json")
            total = 0
            offset = 0

            def _open_writer(file_path: str = file_path):
                return open(file_path, "w", encoding="utf-8")

            with await asyncio.to_thread(_open_writer) as raw:
                writer = BackupFileWriter(raw)
                while True:
                    cursor = self._mongo_db[table].find({}).skip(offset).limit(page_size)
                    docs = await cursor.to_list(length=page_size)
                    if not docs:
                        break
                    writer.write_rows([dict(d) for d in docs])
                    total += len(docs)
                    if len(docs) < page_size:
                        break
                    offset += page_size
                writer.finish()

            counts[table] = total

        return counts

    async def restore(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        drop_existing: bool = True,
        chunk_size: int | None = None,
    ) -> dict[str, int]:
        """Restore collections from JSON files and return per-table counts."""
        chunk_size = chunk_size or DEFAULT_PAGE_SIZE
        if tables is None:
            if not os.path.isdir(path):
                return {}
            tables = [
                f[:-5]
                for f in sorted(os.listdir(path))
                if f.endswith(".json") and f != "_db_migrations.json"
            ]

        counts: dict[str, int] = {}
        assert self._mongo_db is not None
        for table in tables:
            file_path = os.path.join(path, f"{table}.json")
            if not os.path.exists(file_path):
                continue

            if drop_existing:
                await self._mongo_db[table].delete_many({})

            restored = 0

            def _open_dump(file_path: str = file_path):
                return open(file_path, "r", encoding="utf-8")

            with await asyncio.to_thread(_open_dump) as raw:
                for page in load_rows_pages(raw, batch_size=chunk_size):
                    docs = [r for r in page if r]
                    if not docs:
                        continue
                    await self._mongo_db[table].insert_many(docs)
                    restored += len(docs)
            counts[table] = restored

        return counts
