from __future__ import annotations

from typing import Any

from renus.db.mutation.ast import (
    Delete,
    DeleteMany,
    Insert,
    InsertMany,
    MutationAST,
    Update,
    UpdateMany,
)
from renus.db.sql.compiler.compiler import SQLCompiled, SQLCompiler
from renus.db.sql.dialect.base import SQLDialect


class SQLMutationCompiler:

    def __init__(self, dialect: SQLDialect) -> None:
        """Bind a dialect and prepare the query compiler.

        Parameters
        ----------
        dialect:
            SQL dialect used for quoting and placeholders.
        """
        self.dialect = dialect
        self.qc = SQLCompiler(dialect)

    def compile(self, m: MutationAST) -> SQLCompiled:
        """Compile a mutation AST into SQL."""
        source = m.source
        meta = getattr(source, "__db_metadata__", None)
        table_name = meta.table if meta else getattr(source, "table", source.__name__.lower())
        quoted_table = self.dialect.quote(table_name)

        if isinstance(m, Insert):
            return self._compile_insert(quoted_table, m, meta)

        if isinstance(m, InsertMany):
            return self._compile_insert_many(quoted_table, m, meta)

        if isinstance(m, (Update, UpdateMany)):
            return self._compile_update(quoted_table, m, meta)

        if isinstance(m, (Delete, DeleteMany)):
            return self._compile_delete(quoted_table, m, meta)


        raise NotImplementedError(f"Unsupported mutation type: {type(m).__name__}")

    def _encode_field_value(self, meta: Any, name: str, value: Any) -> Any:
        field_meta = meta.fields.get(name) if meta is not None else None
        return self.dialect.encode_value(value, field_meta)

    def _column_name(self, meta: Any, name: str) -> str:
        field_meta = meta.fields.get(name) if meta is not None else None
        return field_meta.column_name if field_meta is not None else name

    def _compile_insert(self, table: str, m: Insert, meta: Any = None) -> SQLCompiled:
        cols = list(m.values.keys())
        col_names = ", ".join(
            self.dialect.quote(self._column_name(meta, c)) for c in cols
        )
        val_placeholders = self.dialect.placeholders(len(cols))
        sql = f"INSERT INTO {table} ({col_names}) VALUES ({val_placeholders})"
        params = [self._encode_field_value(meta, c, m.values[c]) for c in cols]
        return SQLCompiled(sql, tuple(params), meta=meta)

    def _compile_insert_many(self, table: str, m: InsertMany, meta: Any = None) -> SQLCompiled:
        if not m.records:
            return SQLCompiled("", (), meta=meta)

        cols = list(m.records[0])
        if any(set(record) != set(cols) for record in m.records[1:]):
            raise ValueError("InsertMany records must have identical fields")
        col_names = ", ".join(
            self.dialect.quote(self._column_name(meta, c)) for c in cols
        )
        single_row_placeholders = f"({self.dialect.placeholders(len(cols))})"
        all_placeholders = ", ".join(single_row_placeholders for _ in m.records)

        sql = f"INSERT INTO {table} ({col_names}) VALUES {all_placeholders}"

        params: list[Any] = []
        for rec in m.records:
            for c in cols:
                params.append(self._encode_field_value(meta, c, rec.get(c)))

        return SQLCompiled(sql, tuple(params), meta=meta)

    def _compile_update(self, table: str, m: Update | UpdateMany, meta: Any = None) -> SQLCompiled:
        set_clauses = [
            f"{self.dialect.quote(self._column_name(meta, k))} = {self.dialect.placeholder}"
            for k in m.values
        ]
        params: list[Any] = [
            self._encode_field_value(meta, name, value)
            for name, value in m.values.items()
        ]

        where_clauses: list[str] = []
        for cond in m.filters:
            s, p = self.qc._condition(cond)
            where_clauses.append(s)
            params.extend(p)

        sql = f"UPDATE {table} SET {', '.join(set_clauses)}"
        if where_clauses:
            sql += f" WHERE {' AND '.join(where_clauses)}"

        if isinstance(m, Update):
            sql += " LIMIT 1"

        return SQLCompiled(sql, tuple(params), meta=meta)

    def _compile_delete(self, table: str, m: Delete | DeleteMany, meta: Any = None) -> SQLCompiled:
        where_clauses: list[str] = []
        params: list[Any] = []

        for cond in m.filters:
            s, p = self.qc._condition(cond)
            where_clauses.append(s)
            params.extend(p)

        sql = f"DELETE FROM {table}"
        if where_clauses:
            sql += f" WHERE {' AND '.join(where_clauses)}"

        if isinstance(m, Delete):
            sql += " LIMIT 1"

        return SQLCompiled(sql, tuple(params), meta=meta)

