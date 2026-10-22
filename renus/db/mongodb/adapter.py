from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterable
from types import TracebackType
from typing import Any, ClassVar

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
from renus.db.mongodb.dialect import MongoDialect
from renus.db.mutation.ast import MutationAST
from renus.db.query.ast import QueryAST
from renus.datastructures.id import ID, is_identity

try:
    from pymongo import AsyncMongoClient, ReturnDocument
    from pymongo.errors import DuplicateKeyError as PyMongoDuplicateKeyError
except ImportError:
    AsyncMongoClient = None
    ReturnDocument = None
    PyMongoDuplicateKeyError = None


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

    def __init__(self, config: dict | None = None) -> None:
        """Initialize the MongoDB adapter.

        Parameters
        ----------
        config:
            Optional connection configuration dictionary. Defaults to empty.
        """
        self.config = config if config else {}
        self.dialect = MongoDialect()
        self.compiler = MongoCompiler(self.dialect)
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

        if AsyncMongoClient is None:
            raise ConnectionError(
                "pymongo>=4.9 is required for native async MongoDB access. Install 'pymongo'."
            )

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

    def _normalize_joined_documents(
        self,
        docs: list[dict[str, Any]],
        mongo_query: MongoCompiledQuery,
    ) -> list[dict[str, Any]]:
        """Normalize lookup arrays recursively to relationship cardinality."""
        if not mongo_query.joined or not mongo_query.meta:
            return docs

        def normalize(value: dict[str, Any], meta: Any) -> dict[str, Any]:
            data = dict(value)
            for name, rel in getattr(meta, "relationships", {}).items():
                if name not in data:
                    continue
                target_meta = getattr(rel.target, "__db_metadata__", None)
                raw = data[name]
                if target_meta is None:
                    continue
                if rel.is_collection:
                    items = raw if isinstance(raw, list) else []
                    data[name] = [
                        normalize(dict(item), target_meta)
                        for item in items
                        if isinstance(item, dict)
                    ]
                else:
                    item = raw[0] if isinstance(raw, list) and raw else raw
                    data[name] = (
                        normalize(dict(item), target_meta)
                        if isinstance(item, dict)
                        else None
                    )
            if "_id" in data:
                data.setdefault("id", data.pop("_id"))
            return self.dialect.decode_value(data, meta)

        root_meta = mongo_query.meta
        return [normalize(doc, root_meta) for doc in docs]

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
            meta = getattr(mongo_query, "meta", None)
            normalized_docs = self._normalize_joined_documents(
                [dict(d) for d in docs], mongo_query
            )
            for d in normalized_docs:
                # Drop framework-reserved pipeline artifacts (e.g. lookup
                # arrays used for $elemMatch filtering) before hydration;
                # they are internal and must not reach model init.
                doc = {
                    k: v
                    for k, v in dict(d).items()
                    if not str(k).startswith("__renus_")
                }
                if "_id" in doc:
                    if "id" not in doc:
                        doc["id"] = doc["_id"]
                    doc.pop("_id", None)
                
                if meta and getattr(meta, "fields", None):
                    decoded = self.dialect.decode_value(doc, meta)
                else:
                    decoded = self.dialect._decode_native(doc)
                results.append(decoded)

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
                doc = dict(filt_or_doc)
                auto_inc_field = extra.get("auto_inc_field") if isinstance(extra, dict) else None
                generated_value = None
                generated_field = None
                if auto_inc_field is not None and auto_inc_field not in filt_or_doc:
                    generated_value = await self._next_sequence(coll.name, session)
                    generated_field = auto_inc_field
                    if auto_inc_field == "id":
                        doc["_id"] = generated_value
                    else:
                        doc[auto_inc_field] = generated_value

                res = await coll.insert_one(doc, session=session)
                generated: dict[str, Any] | None = None
                if generated_field is not None and generated_field != "id":
                    generated = {generated_field: generated_value}

                meta = extra.get("meta") if isinstance(extra, dict) else None
                pk_meta = meta.fields.get(meta.primary_key_field) if meta and meta.fields else None
                last_id = self.dialect.decode_value(res.inserted_id, pk_meta)

                return MutationResult(
                    rows_affected=1,
                    last_id=last_id,
                    generated=generated,
                )

            if op == "insert_many":
                docs = filt_or_doc.get("docs", [])
                auto_inc_field = extra.get("auto_inc_field") if isinstance(extra, dict) else None
                new_docs = []
                generated_values: list[Any] = []
                for d in docs:
                    dd = dict(d)
                    stored_field = "_id" if auto_inc_field == "id" else auto_inc_field
                    if auto_inc_field is not None and stored_field not in dd:
                        next_id = await self._next_sequence(coll.name, session)
                        dd[stored_field] = next_id
                        generated_values.append(next_id)
                    elif auto_inc_field is not None:
                        generated_values.append(dd[stored_field])
                    new_docs.append(dd)

                res = await coll.insert_many(new_docs, session=session)
                meta = extra.get("meta") if isinstance(extra, dict) else None
                pk_meta = meta.fields.get(meta.primary_key_field) if meta and meta.fields else None
                ids = [self.dialect.decode_value(i, pk_meta) for i in res.inserted_ids]
                generated: dict[str, Any] = {"ids": ids}
                if auto_inc_field is not None and auto_inc_field != "id":
                    generated[auto_inc_field] = generated_values
                return MutationResult(
                    rows_affected=len(res.inserted_ids),
                    generated=generated,
                )

            if op == "update_one":
                if isinstance(extra, dict) and "_id" in extra.get("$set", {}):
                    return await self._update_reassign_pk(coll, filt_or_doc, extra["$set"], session, single=True)
                res = await coll.update_one(filt_or_doc, extra, session=session)
                return MutationResult(rows_affected=res.modified_count)

            if op == "update_many":
                if isinstance(extra, dict) and "_id" in extra.get("$set", {}):
                    return await self._update_reassign_pk(coll, filt_or_doc, extra["$set"], session, single=False)
                res = await coll.update_many(filt_or_doc, extra, session=session)
                return MutationResult(rows_affected=res.modified_count)

            if op == "delete_one":
                res = await coll.delete_one(filt_or_doc, session=session)
                return MutationResult(rows_affected=res.deleted_count)

            if op == "delete_many":
                res = await coll.delete_many(filt_or_doc, session=session)
                return MutationResult(rows_affected=res.deleted_count)


            raise NotImplementedError(f"Unsupported MongoDB operation: {op}")
        except Exception as e:
            raise errors.translate_driver_error("MongoDB", "mongodb", e, "mutation") from e

    async def _next_sequence(self, coll_name: str, session: Any) -> int:
        """Atomically allocate the next integer id for a collection.

        Uses an atomic ``$inc`` on a shared ``__counters__`` collection so
        concurrent inserts receive distinct ids.
        """
        if ReturnDocument is None:
            raise ConnectionError(
                "pymongo>=4.9 is required for native async MongoDB access. Install 'pymongo'."
            )

        counters = self._mongo_db["__counters__"]
        counter = await counters.find_one_and_update(
            {"_id": f"seq_{coll_name}"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        return counter["seq"]

    async def _update_reassign_pk(self, coll, filt, set_doc, session, *, single):
        docs = await coll.find(filt, session=session).to_list(length=1 if single else 2)
        if len(docs) > 1:
            raise errors.DuplicateKeyError(
                "MongoDB reassign error: multiple documents cannot be reassigned to the same unique '_id'"
            )
        if not docs:
            return MutationResult(rows_affected=0)
        doc = docs[0]
        old_id = doc.get("_id")
        new_id = set_doc["_id"]
        if old_id == new_id:
            return MutationResult(rows_affected=0)
        replacement = {k: v for k, v in set_doc.items() if k != "_id"}
        new_doc = dict(doc)
        new_doc.update(replacement)
        new_doc["_id"] = new_id
        await coll.insert_one(new_doc, session=session)
        await coll.delete_one({"_id": old_id}, session=session)
        return MutationResult(rows_affected=1)

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
