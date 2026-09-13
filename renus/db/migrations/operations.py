from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from renus.db.sql.dialect.base import SQLDialect

__all__ = [
    "Column",
    "TableDefinition",
    "add_column_sql",
    "column_to_sql",
    "create_index_sql",
    "create_table_sql",
    "drop_column_sql",
    "drop_index_sql",
    "drop_table_sql",
    "rename_column_sql",
    "rename_table_sql",
]

@dataclass
class Column:
    """Describe a single column for schema DDL."""

    name: str
    type: str | type = "str"
    nullable: bool = True
    primary_key: bool = False
    generated: bool = False
    unique: bool = False
    default: Any = None
    foreign_key: str | None = None
    on_delete: str | None = None
    on_update: str | None = None
    comment: str | None = None

@dataclass
class TableDefinition:
    """Describe a table and its columns."""

    name: str
    columns: list[Column] = field(default_factory=list)

def _resolve_sql_type(col: Column, dialect: SQLDialect) -> str:
    dialect_name = getattr(dialect, "__class__", type(dialect)).__name__.lower()
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

def column_to_sql(col: Column, dialect: SQLDialect) -> str:
    """Render a column definition as SQL."""
    quoted_name = dialect.quote(col.name)
    type_str = _resolve_sql_type(col, dialect)

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
    table: str,
    columns: Iterable[Column],
    dialect: SQLDialect,
    if_not_exists: bool = True,
) -> str:
    """Build a ``CREATE TABLE`` statement."""
    quoted_table = dialect.quote(table)
    if_clause = "IF NOT EXISTS " if if_not_exists else ""
    col_defs = [column_to_sql(c, dialect) for c in columns]

    for c in columns:
        if c.foreign_key and "." in c.foreign_key:
            ref_table, ref_col = c.foreign_key.split(".", 1)
            fk_clause = (
                f"FOREIGN KEY ({dialect.quote(c.name)}) "
                f"REFERENCES {dialect.quote(ref_table)}({dialect.quote(ref_col)})"
            )
            if c.on_delete:
                fk_clause += f" ON DELETE {c.on_delete.upper()}"
            if c.on_update:
                fk_clause += f" ON UPDATE {c.on_update.upper()}"
            col_defs.append(fk_clause)

    return f"CREATE TABLE {if_clause}{quoted_table} ({', '.join(col_defs)});"

def drop_table_sql(
    table: str,
    dialect: SQLDialect,
    if_exists: bool = True,
) -> str:
    """Build a ``DROP TABLE`` statement."""
    quoted_table = dialect.quote(table)
    if_clause = "IF EXISTS " if if_exists else ""
    return f"DROP TABLE {if_clause}{quoted_table};"

def add_column_sql(
    table: str,
    column: Column,
    dialect: SQLDialect,
) -> str:
    """Build an ``ALTER TABLE ... ADD COLUMN`` statement."""
    quoted_table = dialect.quote(table)
    col_def = column_to_sql(column, dialect)
    return f"ALTER TABLE {quoted_table} ADD COLUMN {col_def};"

def drop_column_sql(
    table: str,
    column_name: str,
    dialect: SQLDialect,
) -> str:
    """Build an ``ALTER TABLE ... DROP COLUMN`` statement."""
    quoted_table = dialect.quote(table)
    quoted_col = dialect.quote(column_name)
    return f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_col};"

def rename_column_sql(
    table: str,
    old_name: str,
    new_name: str,
    dialect: SQLDialect,
) -> str:
    """Build an ``ALTER TABLE ... RENAME COLUMN`` statement."""
    quoted_table = dialect.quote(table)
    quoted_old = dialect.quote(old_name)
    quoted_new = dialect.quote(new_name)
    return f"ALTER TABLE {quoted_table} RENAME COLUMN {quoted_old} TO {quoted_new};"

def rename_table_sql(
    old_name: str,
    new_name: str,
    dialect: SQLDialect,
) -> str:
    """Build an ``ALTER TABLE ... RENAME TO`` statement."""
    quoted_old = dialect.quote(old_name)
    quoted_new = dialect.quote(new_name)
    return f"ALTER TABLE {quoted_old} RENAME TO {quoted_new};"

def create_index_sql(
    table: str,
    name: str,
    fields: Iterable[str],
    unique: bool,
    dialect: SQLDialect,
) -> str:
    """Build a ``CREATE INDEX`` statement."""
    quoted_table = dialect.quote(table)
    quoted_name = dialect.quote(name)
    quoted_fields = ", ".join(dialect.quote(f) for f in fields)
    unique_str = "UNIQUE " if unique else ""
    dialect_name = getattr(dialect, "__class__", type(dialect)).__name__.lower()
    if "sqlite" in dialect_name:
        return f"CREATE {unique_str}INDEX IF NOT EXISTS {quoted_name} ON {quoted_table} ({quoted_fields});"
    return f"CREATE {unique_str}INDEX {quoted_name} ON {quoted_table} ({quoted_fields});"

def drop_index_sql(
    table: str,
    name: str,
    dialect: SQLDialect,
) -> str:
    """Build a ``DROP INDEX`` statement."""
    quoted_name = dialect.quote(name)
    quoted_table = dialect.quote(table)
    dialect_name = getattr(dialect, "__class__", type(dialect)).__name__.lower()
    if "sqlite" in dialect_name:
        return f"DROP INDEX IF EXISTS {quoted_name};"
    return f"DROP INDEX {quoted_name} ON {quoted_table};"
