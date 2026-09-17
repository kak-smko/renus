from __future__ import annotations

from typing import Any

from renus.db.metadata.core import FieldMetadata
from renus.db.sql.dialect.base import SQLDialect

__all__ = ["MySQLDialect"]

class MySQLDialect(SQLDialect):

    placeholder: str = "%s"

    def quote(self, name: str) -> str:
        """Quote an identifier using MySQL backticks."""
        escaped = name.replace("`", "``")
        return f"`{escaped}`"

    def type_to_sql(self, field_meta: FieldMetadata) -> str:
        """Map a field metadata type to a MySQL SQL type."""

        if (
            field_meta.primary_key
            and field_meta.database.auto_inc
            and field_meta.generated
        ):
            return "INT AUTO_INCREMENT PRIMARY KEY"

        st = field_meta.storage_type
        if isinstance(st, type):
            if issubclass(st, bool):
                return "TINYINT(1)"
            if issubclass(st, int):
                return "INT"
            if issubclass(st, float):
                return "DOUBLE"
            if issubclass(st, (bytes, bytearray)):
                return "LONGBLOB"

        type_name = str(field_meta.inferred_type).lower()
        if "datetime" in type_name:
            return "DATETIME"
        if "date" in type_name:
            return "DATE"
        if "time" in type_name:
            return "TIME"
        if "uuid" in type_name:
            return "CHAR(36)"
        if "decimal" in type_name:
            return "DECIMAL(18, 4)"
        if "dict" in type_name or "list" in type_name:
            return "JSON"

        return "VARCHAR(255)"

    def upsert_sql(
        self,
        table: str,
        conflict_target: tuple[str, ...],
        create_values: dict[str, Any],
        update_values: dict[str, Any],
    ) -> tuple[str, list[Any]]:
        """Build an upsert SQL statement using ON DUPLICATE KEY UPDATE."""
        cols = list(create_values.keys())
        col_names = ", ".join(self.quote(c) for c in cols)
        val_placeholders = ", ".join(self.placeholder for _ in cols)
        params: list[Any] = [create_values[c] for c in cols]

        set_clauses: list[str] = []
        for c in update_values:
            set_clauses.append(f"{self.quote(c)} = {self.placeholder}")
            params.append(update_values[c])

        sql = f"INSERT INTO {table} ({col_names}) VALUES ({val_placeholders}) "
        if set_clauses:
            sql += f"ON DUPLICATE KEY UPDATE {', '.join(set_clauses)}"

        return sql, params
