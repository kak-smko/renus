from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from renus.db.core import convert
from renus.db.metadata.core import FieldMetadata
from renus.datastructures.id import ID, is_identity

if TYPE_CHECKING:
    from renus.db.migrations.operations import Column



class SQLDialect(ABC):
    placeholder: str = "?"

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
            sql += f" LIMIT {int(limit)}"
        elif offset is not None:
            sql += " LIMIT -1"
        if offset is not None:
            sql += f" OFFSET {int(offset)}"
        return sql

    @abstractmethod
    def type_to_sql(self, field_meta: FieldMetadata) -> str:
        """Return the SQL column type for a field's metadata."""
        pass

    @staticmethod
    def _max_text_length(field_meta: FieldMetadata) -> int | None:
        """Return a declared ``MaxLen`` value for a field, if present."""
        validation = getattr(field_meta, "validation", None)
        for rule in getattr(validation, "rules", ()):
            if rule.__class__.__name__ != "MaxLen":
                continue
            length = getattr(rule, "l", None)
            if isinstance(length, int):
                return length
        return None

    def _resolve_sql_type(self, col: Column) -> str:
        dialect_name = type(self).__name__.lower()
        is_mysql = "mysql" in dialect_name

        if isinstance(col.type, str):
            raw_type = col.type.strip()

            lower = raw_type.lower()
            if lower in ("int", "integer","id"):
                if col.primary_key and col.generated and col.auto_inc:
                    return (
                        "INT AUTO_INCREMENT PRIMARY KEY"
                        if is_mysql
                        else "INTEGER PRIMARY KEY AUTOINCREMENT"
                    )
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
                if col.primary_key and col.generated and col.auto_inc:
                    return (
                        "INT AUTO_INCREMENT PRIMARY KEY"
                        if is_mysql
                        else "INTEGER PRIMARY KEY AUTOINCREMENT"
                    )
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

    def encode_value(self, value: Any, field_meta: Any = None) -> Any:
        """Encode a value for storage.

        An ``ID`` is stored in its portable text form, matching the SQL text
        column a relational backend uses for identity values.
        """
        if isinstance(value, ID):
            return None if value.value is None else str(value)
        return convert.encode_value(value, field_meta)

    def decode_value(self, value: Any, field_meta: Any = None) -> Any:
        """Decode a stored value back into its Python form."""
        if value is not None and field_meta is not None and is_identity(
            field_meta.inferred_type
        ):
            return ID(value)
        return convert.decode_value(value, field_meta)

    def decode_row(self, row: dict[str, Any], meta: Any = None) -> dict[str, Any]:
        """Decode a database row into a dictionary with correct types according to model meta."""
        data = dict(row)
        if meta is None or not hasattr(meta, "fields"):
            return data
        for fname, fmeta in meta.fields.items():
            col = getattr(fmeta, "column_name", fname)
            if col in data:
                val = data[col]
            elif fname in data:
                val = data[fname]
            else:
                continue
            data[fname] = self.decode_value(val, fmeta)
        return data
