from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from renus.db.metadata.core import FieldMetadata

if TYPE_CHECKING:
    from renus.db.migrations.operations import Column

__all__ = ["SQLDialect"]

class SQLDialect(ABC):

    placeholder: str = "?"
    supports_returning: bool = False

    @abstractmethod
    def quote(self, name: str) -> str:
        """Quote an identifier for this dialect."""
        pass

    def placeholders(self, n: int) -> str:
        """Return a comma-separated list of ``n`` placeholders."""
        return ", ".join(self.placeholder for _ in range(n))

    def limit_offset(
        self,
        sql: str,
        limit: int | None,
        offset: int | None,
    ) -> str:
        """Append LIMIT and OFFSET clauses to ``sql``."""
        if limit is not None:
            sql += f" LIMIT {limit}"
        if offset is not None:
            sql += f" OFFSET {offset}"
        return sql

    @abstractmethod
    def type_to_sql(self, field_meta: FieldMetadata) -> str:
        """Return the SQL column type for a field's metadata."""
        pass

    @abstractmethod
    def upsert_sql(
        self,
        table: str,
        conflict_target: tuple[str, ...],
        create_values: dict[str, Any],
        update_values: dict[str, Any],
        returning: tuple[str, ...] | None = None,
    ) -> tuple[str, list[Any]]:
        """Build an upsert statement with conflict handling."""
        pass

    def returning_clause(self, cols: tuple[str, ...] | None) -> str:
        """Return a RETURNING clause when columns and dialect support it."""
        if self.supports_returning and cols:
            return f" RETURNING {', '.join(self.quote(c) for c in cols)}"
        return ""

    def _resolve_sql_type(self, col: Column) -> str:
        dialect_name = type(self).__name__.lower()
        is_mysql = "mysql" in dialect_name

        if isinstance(col.type, str):
            raw_type = col.type.strip()

            lower = raw_type.lower()
            if lower in ("int", "integer"):
                if col.primary_key and col.generated:
                    return "INT AUTO_INCREMENT PRIMARY KEY" if is_mysql else "INTEGER PRIMARY KEY AUTOINCREMENT"
                return "INT" if is_mysql else "INTEGER"
            if lower in ("str", "string", "varchar"):
                return "VARCHAR(255)" if is_mysql else "TEXT"
            if lower in ("text", "longtext"):
                return "LONGTEXT" if is_mysql else "TEXT"
            if lower in ("float", "double", "real"):
                return "DOUBLE" if is_mysql else "REAL"
            if lower in ("bool", "boolean"):
                return "TINYINT(1)" if is_mysql else "INTEGER"
            if lower in ("datetime", "timestamp"):
                return "DATETIME" if is_mysql else "TEXT"
            if lower == "date":
                return "DATE" if is_mysql else "TEXT"
            if lower == "time":
                return "TIME" if is_mysql else "TEXT"
            if lower == "uuid":
                return "CHAR(36)" if is_mysql else "TEXT"
            if lower == "json":
                return "JSON" if is_mysql else "TEXT"
            if lower in ("blob", "bytes"):
                return "LONGBLOB" if is_mysql else "BLOB"
            return raw_type

        if isinstance(col.type, type):
            if issubclass(col.type, bool):
                return "TINYINT(1)" if is_mysql else "INTEGER"
            if issubclass(col.type, int):
                if col.primary_key and col.generated:
                    return "INT AUTO_INCREMENT PRIMARY KEY" if is_mysql else "INTEGER PRIMARY KEY AUTOINCREMENT"
                return "INT" if is_mysql else "INTEGER"
            if issubclass(col.type, float):
                return "DOUBLE" if is_mysql else "REAL"
            if issubclass(col.type, (bytes, bytearray)):
                return "LONGBLOB" if is_mysql else "BLOB"
            if issubclass(col.type, datetime):
                return "DATETIME" if is_mysql else "TEXT"
            if issubclass(col.type, date):
                return "DATE" if is_mysql else "TEXT"
            if issubclass(col.type, time):
                return "TIME" if is_mysql else "TEXT"
            if issubclass(col.type, UUID):
                return "CHAR(36)" if is_mysql else "TEXT"
            if issubclass(col.type, Decimal):
                return "DECIMAL(18, 4)" if is_mysql else "TEXT"
            if issubclass(col.type, (dict, list)):
                return "JSON" if is_mysql else "TEXT"
            return "VARCHAR(255)" if is_mysql else "TEXT"

        return "TEXT"

    def column_to_sql(self, col: Column) -> str:
        """Render a column definition as SQL."""
        quoted_name = self.quote(col.name)
        type_str = self._resolve_sql_type(col)

        if "PRIMARY KEY" in type_str:
            return f"{quoted_name} {type_str}"

        parts = [quoted_name, type_str]

        if col.primary_key:
            parts.append("PRIMARY KEY")

        if not col.nullable:
            parts.append("NOT NULL")
        elif not col.primary_key:
            parts.append("NULL")

        if col.unique and not col.primary_key:
            parts.append("UNIQUE")

        if col.default is not None:
            if isinstance(col.default, bool):
                parts.append(f"DEFAULT {1 if col.default else 0}")
            elif isinstance(col.default, (int, float)):
                parts.append(f"DEFAULT {col.default}")
            else:
                escaped_default = str(col.default).replace("'", "''")
                parts.append(f"DEFAULT '{escaped_default}'")

        return " ".join(parts)

    def create_table_sql(
        self,
        table: str,
        columns: Iterable[Column],
        if_not_exists: bool = True,
    ) -> str:
        """Build a ``CREATE TABLE`` statement."""
        quoted_table = self.quote(table)
        if_clause = "IF NOT EXISTS " if if_not_exists else ""
        col_defs = [self.column_to_sql(c) for c in columns]
        columns = list(columns)

        for c in columns:
            if c.foreign_key and "." in c.foreign_key:
                ref_table, ref_col = c.foreign_key.split(".", 1)
                fk_clause = (
                    f"FOREIGN KEY ({self.quote(c.name)}) "
                    f"REFERENCES {self.quote(ref_table)}({self.quote(ref_col)})"
                )
                if c.on_delete:
                    fk_clause += f" ON DELETE {c.on_delete.upper()}"
                if c.on_update:
                    fk_clause += f" ON UPDATE {c.on_update.upper()}"
                col_defs.append(fk_clause)

        return f"CREATE TABLE {if_clause}{quoted_table} ({', '.join(col_defs)});"

    def drop_table_sql(
        self,
        table: str,
        if_exists: bool = True,
    ) -> str:
        """Build a ``DROP TABLE`` statement."""
        quoted_table = self.quote(table)
        if_clause = "IF EXISTS " if if_exists else ""
        return f"DROP TABLE {if_clause}{quoted_table};"

    def add_column_sql(
        self,
        table: str,
        column: Column,
    ) -> str:
        """Build an ``ALTER TABLE ... ADD COLUMN`` statement."""
        quoted_table = self.quote(table)
        col_def = self.column_to_sql(column)
        return f"ALTER TABLE {quoted_table} ADD COLUMN {col_def};"

    def drop_column_sql(
        self,
        table: str,
        column_name: str,
    ) -> str:
        """Build an ``ALTER TABLE ... DROP COLUMN`` statement."""
        quoted_table = self.quote(table)
        quoted_col = self.quote(column_name)
        return f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_col};"

    def rename_column_sql(
        self,
        table: str,
        old_name: str,
        new_name: str,
    ) -> str:
        """Build an ``ALTER TABLE ... RENAME COLUMN`` statement."""
        quoted_table = self.quote(table)
        quoted_old = self.quote(old_name)
        quoted_new = self.quote(new_name)
        return f"ALTER TABLE {quoted_table} RENAME COLUMN {quoted_old} TO {quoted_new};"

    def rename_table_sql(
        self,
        old_name: str,
        new_name: str,
    ) -> str:
        """Build an ``ALTER TABLE ... RENAME TO`` statement."""
        quoted_old = self.quote(old_name)
        quoted_new = self.quote(new_name)
        return f"ALTER TABLE {quoted_old} RENAME TO {quoted_new};"

    def create_index_sql(
        self,
        table: str,
        name: str,
        fields: Iterable[str],
        unique: bool,
    ) -> str:
        """Build a ``CREATE INDEX`` statement."""
        quoted_table = self.quote(table)
        quoted_name = self.quote(name)
        quoted_fields = ", ".join(self.quote(f) for f in fields)
        unique_str = "UNIQUE " if unique else ""
        dialect_name = type(self).__name__.lower()
        if "sqlite" in dialect_name:
            return f"CREATE {unique_str}INDEX IF NOT EXISTS {quoted_name} ON {quoted_table} ({quoted_fields});"
        return f"CREATE {unique_str}INDEX {quoted_name} ON {quoted_table} ({quoted_fields});"

    def drop_index_sql(
        self,
        table: str,
        name: str,
    ) -> str:
        """Build a ``DROP INDEX`` statement."""
        quoted_name = self.quote(name)
        quoted_table = self.quote(table)
        dialect_name = type(self).__name__.lower()
        if "sqlite" in dialect_name:
            return f"DROP INDEX IF EXISTS {quoted_name};"
        return f"DROP INDEX {quoted_name} ON {quoted_table};"
