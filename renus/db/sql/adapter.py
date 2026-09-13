from __future__ import annotations

import asyncio
import os
from typing import Any, ClassVar

from renus.db.core.adapter import AsyncDatabaseAdapter
from renus.db.core.backup import DEFAULT_PAGE_SIZE, BackupFileWriter, load_rows_pages
from renus.db.migrations.operations import (
    add_column_sql,
    create_index_sql,
    create_table_sql,
    drop_column_sql,
    drop_index_sql,
    drop_table_sql,
    rename_column_sql,
    rename_table_sql,
)
from renus.db.mutation.ast import MutationAST
from renus.db.query.ast import QueryAST
from renus.db.repository.core import RawStatement
from renus.db.sql.compiler.compiler import SQLCompiled, SQLCompiler
from renus.db.sql.dialect.base import SQLDialect
from renus.db.sql.mutation import SQLMutationCompiler

__all__ = ["SQLAdapter"]

class SQLAdapter(AsyncDatabaseAdapter):

    dialect: SQLDialect
    compiler: SQLCompiler
    mutation_compiler: SQLMutationCompiler

    def compile_query(self, ast: QueryAST) -> SQLCompiled:
        """Compile a query AST into SQL."""
        return self.compiler.compile(ast)

    def compile_mutation(self, ast: MutationAST) -> SQLCompiled:
        """Compile a mutation AST into SQL."""
        return self.mutation_compiler.compile(ast)

    @staticmethod
    def _is_read_statement(sql: str) -> bool:
        head = sql.lstrip()[:24].upper()
        return head.startswith(
            ("SELECT", "PRAGMA", "WITH", "EXPLAIN", "SHOW", "DESC", "VACUUM")
        )

    _raw_embedded_key_type: ClassVar[str] = "TEXT"

    _raw_embedded_pos_type: ClassVar[str] = "INTEGER"

    _raw_embedded_table_options: ClassVar[str] = ""

    def _raw_embedded_table_sql(self, meta: Any, rel_name: str, rel: Any) -> str:
        quoted_table = self.dialect.quote(f"{meta.table}_{rel_name}")
        parent_table = self.dialect.quote(meta.table)
        parent_pk = self.dialect.quote(meta.primary_key_field)
        pk_fmeta = meta.fields.get(meta.primary_key_field)
        pk_type = (
            self.dialect.type_to_sql(pk_fmeta).split()[0]
            if pk_fmeta is not None
            else "INTEGER"
        )
        pid = self.dialect.quote("parent_id")
        if rel.target is dict:
            key_col = self.dialect.quote("key")
            value_col = self.dialect.quote("value")
            cols = [
                f"{pid} {pk_type} NOT NULL",
                f"{key_col} {self._raw_embedded_key_type} NOT NULL",
                f"{value_col} TEXT NULL",
                f"PRIMARY KEY ({pid}, {key_col})",
            ]
        else:
            pos_col = self.dialect.quote("pos")
            value_col = self.dialect.quote("value")
            cols = [
                f"{pid} {pk_type} NOT NULL",
                f"{pos_col} {self._raw_embedded_pos_type} NOT NULL",
                f"{value_col} TEXT NULL",
                f"PRIMARY KEY ({pid}, {pos_col})",
            ]
        cols.append(
            f"FOREIGN KEY ({pid}) REFERENCES {parent_table}({parent_pk}) "
            f"ON DELETE CASCADE"
        )
        return (
            f"CREATE TABLE {self._ddl_if_not_exists} {quoted_table} "
            f"({', '.join(cols)}){self._raw_embedded_table_options};"
        )

    _ddl_if_not_exists: ClassVar[str] = "IF NOT EXISTS"

    _index_if_not_exists: ClassVar[str] = "IF NOT EXISTS"

    _table_options: ClassVar[str] = ""

    async def _open_schema_session(self) -> Any:
        raise NotImplementedError

    async def _execute_ddl(self, sql: str) -> None:
        raise NotImplementedError

    async def _execute_index_ddl(self, sql: str) -> None:
        await self._execute_ddl(sql)

    async def _commit_schema(self) -> None:
        raise NotImplementedError

    async def _close_schema_session(self) -> None:
        raise NotImplementedError

    def _main_table_sql(self, meta: Any) -> str:
        quoted_table = self.dialect.quote(meta.table)
        col_defs: list[str] = []

        for fmeta in meta.fields.values():
            col_name = self.dialect.quote(fmeta.column_name)
            type_def = self.dialect.type_to_sql(fmeta)

            if "PRIMARY KEY" in type_def:
                col_defs.append(f"{col_name} {type_def}")
                continue

            pk_constraint = " PRIMARY KEY" if fmeta.primary_key else ""
            null_constraint = " NULL" if fmeta.nullable else " NOT NULL"
            unique_constraint = " UNIQUE" if fmeta.unique else ""
            default_constraint = ""
            if fmeta.has_default and fmeta.default is not None:
                if isinstance(fmeta.default, bool):
                    default_constraint = f" DEFAULT {1 if fmeta.default else 0}"
                elif isinstance(fmeta.default, (int, float)):
                    default_constraint = f" DEFAULT {fmeta.default}"
                else:
                    default_constraint = f" DEFAULT '{fmeta.default}'"

            col_defs.append(
                f"{col_name} {type_def}{pk_constraint}{null_constraint}"
                f"{unique_constraint}{default_constraint}"
            )

        for fmeta in meta.fields.values():
            if fmeta.foreign_key and "." in fmeta.foreign_key:
                ref_table, ref_col = fmeta.foreign_key.split(".", 1)
                col_defs.append(
                    f"FOREIGN KEY ({self.dialect.quote(fmeta.column_name)}) "
                    f"REFERENCES {self.dialect.quote(ref_table)}({self.dialect.quote(ref_col)})"
                )

        return (
            f"CREATE TABLE {self._ddl_if_not_exists} {quoted_table} "
            f"({', '.join(col_defs)}){self._table_options};"
        )

    def _index_sql(self, meta: Any, idx: Any) -> str:
        quoted_table = self.dialect.quote(meta.table)
        unique_str = "UNIQUE " if idx.unique else ""
        idx_name = idx.name or f"idx_{meta.table}_{'_'.join(idx.fields)}"
        quoted_cols = ", ".join(self.dialect.quote(c) for c in idx.fields)
        return (
            f"CREATE {unique_str}INDEX {self._index_if_not_exists} "
            f"{self.dialect.quote(idx_name)} ON {quoted_table} ({quoted_cols});"
        )

    def _embedded_table_sql(self, meta: Any, rel_name: str, rel: Any) -> str:
        embedded_table = self.dialect.quote(f"{meta.table}_{rel_name}")
        parent_table = self.dialect.quote(meta.table)
        parent_pk = self.dialect.quote(meta.primary_key_field)

        child_meta = getattr(rel.target, "__db_metadata__", None)
        if child_meta is None:
            raise ValueError(
                f"Embedded relationship '{rel_name}' targets a model without metadata"
            )

        parent_pk_type = "INTEGER"
        pk_fmeta = meta.fields.get(meta.primary_key_field)
        if pk_fmeta is not None:
            parent_pk_type = self.dialect.type_to_sql(pk_fmeta).split()[0]

        child_cols = [
            f"{self.dialect.quote('parent_id')} {parent_pk_type} NOT NULL"
        ]
        for cfmeta in child_meta.fields.values():
            if cfmeta.primary_key and cfmeta.generated:
                continue
            ccol_name = self.dialect.quote(cfmeta.column_name)
            ctype_def = self.dialect.type_to_sql(cfmeta)
            cnull = " NULL" if cfmeta.nullable else " NOT NULL"
            child_cols.append(f"{ccol_name} {ctype_def}{cnull}")

        child_cols.append(
            f"FOREIGN KEY ({self.dialect.quote('parent_id')}) "
            f"REFERENCES {parent_table}({parent_pk}) ON DELETE CASCADE"
        )

        return (
            f"CREATE TABLE {self._ddl_if_not_exists} {embedded_table} "
            f"({', '.join(child_cols)}){self._table_options};"
        )

    async def create_schema(self, models: Any) -> None:
        """Create tables, indexes, and embedded tables for the given models."""
        await self._open_schema_session()
        try:
            model_list = list(models)

            for model in model_list:
                meta = getattr(model, "__db_metadata__", None)
                if not meta:
                    continue
                await self._execute_ddl(self._main_table_sql(meta))
                for idx in meta.indexes:
                    await self._execute_index_ddl(self._index_sql(meta, idx))

            for model in model_list:
                meta = getattr(model, "__db_metadata__", None)
                if not meta:
                    continue
                for rel_name, rel in meta.relationships.items():
                    if not rel.is_embedded:
                        continue

                    if rel.target is dict or rel.target is list:
                        await self._execute_ddl(
                            self._raw_embedded_table_sql(meta, rel_name, rel)
                        )
                        continue

                    child_meta = getattr(rel.target, "__db_metadata__", None)
                    if not child_meta:
                        continue
                    await self._execute_ddl(
                        self._embedded_table_sql(meta, rel_name, rel)
                    )

            await self._commit_schema()
        finally:
            await self._close_schema_session()

    @staticmethod
    def _resolve_raw_params(
        args: tuple[Any, ...],
        params: tuple[Any, ...] | list[Any] | None,
    ) -> tuple[Any, ...]:
        if params is not None:
            return tuple(params)
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            return tuple(args[0])
        return tuple(args)

    async def execute_raw(
        self,
        raw: Any,
        params: tuple[Any, ...] | list[Any] | None = None,
    ) -> Any:
        """Execute a raw SQL statement, routing reads vs. mutations."""
        if isinstance(raw, RawStatement):
            sql = str(raw.statement)
            p = self._resolve_raw_params(raw.args, params)
        else:
            sql = str(raw)
            p = tuple(params) if params is not None else ()

        if self._is_read_statement(sql):
            return await self.execute_query(SQLCompiled(sql, p))
        return await self.execute_mutation(SQLCompiled(sql, p))

    async def ensure_migration_schema(
        self,
        table_name: str = "_db_migrations",
    ) -> None:
        """Ensure the migration bookkeeping table exists."""
        quoted_table = self.dialect.quote(table_name)
        dialect_name = getattr(self.dialect, "__class__", type(self.dialect)).__name__.lower()
        if "mysql" in dialect_name:
            sql = (
                f"CREATE TABLE IF NOT EXISTS {quoted_table} ("
                f"`version` VARCHAR(255) PRIMARY KEY, "
                f"`name` VARCHAR(255) NOT NULL, "
                f"`applied_at` VARCHAR(64) NOT NULL, "
                f"`checksum` VARCHAR(64) NOT NULL"
                f");"
            )
        else:
            sql = (
                f"CREATE TABLE IF NOT EXISTS {quoted_table} ("
                f'"version" TEXT PRIMARY KEY, '
                f'"name" TEXT NOT NULL, '
                f'"applied_at" TEXT NOT NULL, '
                f'"checksum" TEXT NOT NULL'
                f");"
            )
        await self.execute_mutation(SQLCompiled(sql, ()))

    async def get_applied_migrations(
        self,
        table_name: str = "_db_migrations",
    ) -> list[dict[str, Any]]:
        """Return all applied migration records in version order."""
        await self.ensure_migration_schema(table_name)
        quoted_table = self.dialect.quote(table_name)
        quoted_version = self.dialect.quote("version")
        sql = f"SELECT * FROM {quoted_table} ORDER BY {quoted_version} ASC;"
        return await self.execute_query(SQLCompiled(sql, ()))

    async def record_migration(
        self,
        version: str,
        name: str,
        checksum: str,
        applied_at: str,
        table_name: str = "_db_migrations",
    ) -> None:
        """Store a migration record with its version, name, and checksum."""
        await self.ensure_migration_schema(table_name)
        quoted_table = self.dialect.quote(table_name)
        p = self.dialect.placeholder
        sql = (
            f"INSERT INTO {quoted_table} "
            f"({self.dialect.quote('version')}, {self.dialect.quote('name')}, "
            f"{self.dialect.quote('applied_at')}, {self.dialect.quote('checksum')}) "
            f"VALUES ({p}, {p}, {p}, {p});"
        )
        await self.execute_mutation(
            SQLCompiled(sql, (version, name, applied_at, checksum))
        )

    async def remove_migration(
        self,
        version: str,
        table_name: str = "_db_migrations",
    ) -> None:
        """Delete an applied migration record by version."""
        await self.ensure_migration_schema(table_name)
        quoted_table = self.dialect.quote(table_name)
        p = self.dialect.placeholder
        sql = f"DELETE FROM {quoted_table} WHERE {self.dialect.quote('version')} = {p};"
        await self.execute_mutation(SQLCompiled(sql, (version,)))

    async def create_table(
        self,
        name: str,
        columns: Any,
        if_not_exists: bool = True,
    ) -> None:
        """Create a table from the given name and column definitions."""
        ddl = create_table_sql(name, columns, self.dialect, if_not_exists=if_not_exists)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def drop_table(
        self,
        name: str,
        if_exists: bool = True,
    ) -> None:
        """Drop a table by name."""
        ddl = drop_table_sql(name, self.dialect, if_exists=if_exists)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def add_column(
        self,
        table: str,
        column: Any,
    ) -> None:
        """Add a column to a table."""
        ddl = add_column_sql(table, column, self.dialect)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def drop_column(
        self,
        table: str,
        column_name: str,
    ) -> None:
        """Drop a column from a table."""
        ddl = drop_column_sql(table, column_name, self.dialect)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def rename_column(
        self,
        table: str,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename a column on a table."""
        ddl = rename_column_sql(table, old_name, new_name, self.dialect)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def rename_table(
        self,
        old_name: str,
        new_name: str,
    ) -> None:
        """Rename a table."""
        ddl = rename_table_sql(old_name, new_name, self.dialect)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def create_index(
        self,
        table: str,
        fields: tuple[str, ...] | list[str],
        unique: bool = False,
        name: str | None = None,
    ) -> None:
        """Create an index on the given table and fields."""
        idx_name = name or f"idx_{table}_{'_'.join(fields)}"
        ddl = create_index_sql(table, idx_name, fields, unique, self.dialect)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def drop_index(
        self,
        table: str,
        name: str,
    ) -> None:
        """Drop an index by name."""
        ddl = drop_index_sql(table, name, self.dialect)
        await self.execute_mutation(SQLCompiled(ddl, ()))

    async def tables(self) -> list[str]:
        """Return the names of all user tables in the database."""
        excluded = {"_db_migrations"}
        sql = (
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name;"
        )
        rows = list(await self.execute_query(SQLCompiled(sql, ())))
        return [str(r["name"]) for r in rows if str(r["name"]) not in excluded]

    async def backup(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        page_size: int | None = None,
    ) -> dict[str, int]:
        """Back up tables to JSON files and return row counts per table."""
        page_size = page_size or DEFAULT_PAGE_SIZE
        target_tables = tables if tables is not None else await self.tables()
        os.makedirs(path, exist_ok=True)
        counts: dict[str, int] = {}

        for table in target_tables:
            quoted = self.dialect.quote(table)
            file_path = os.path.join(path, f"{table}.json")
            total = 0
            offset = 0

            def _open_writer(file_path: str = file_path):
                return open(file_path, "w", encoding="utf-8")

            with await asyncio.to_thread(_open_writer) as raw:

                writer = BackupFileWriter(raw)
                while True:
                    sql = f"SELECT * FROM {quoted} LIMIT {page_size} OFFSET {offset};"
                    rows = list(await self.execute_query(SQLCompiled(sql, ())))
                    if not rows:
                        break
                    writer.write_rows(rows)
                    total += len(rows)
                    if len(rows) < page_size:
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
        """Restore tables from JSON backups and return rows inserted per table."""
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
        for table in tables:
            file_path = os.path.join(path, f"{table}.json")
            if not os.path.exists(file_path):
                continue

            if drop_existing:
                quoted_table = self.dialect.quote(table)
                await self.execute_mutation(SQLCompiled(f"DELETE FROM {quoted_table};", ()))

            restored = 0

            def _open_dump(file_path: str = file_path):
                return open(file_path, "r", encoding="utf-8")

            with await asyncio.to_thread(_open_dump) as raw:
                for page in load_rows_pages(raw, batch_size=chunk_size):
                    for record in page:
                        if not record:
                            continue
                        columns = list(record.keys())
                        quoted_cols = ", ".join(self.dialect.quote(c) for c in columns)
                        placeholders = self.dialect.placeholders(len(columns))
                        params = tuple(record[c] for c in columns)
                        sql = (
                            f"INSERT INTO {self.dialect.quote(table)} ({quoted_cols}) "
                            f"VALUES ({placeholders});"
                        )
                        await self.execute_mutation(SQLCompiled(sql, params))
                        restored += 1
            counts[table] = restored

        return counts
