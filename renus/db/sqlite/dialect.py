from __future__ import annotations

from typing import Any

from renus.db.core.state import IdentityKind
from renus.db.metadata.core import FieldMetadata
from renus.db.sql.dialect.base import SQLDialect

__all__ = ["SQLiteDialect"]

class SQLiteDialect(SQLDialect):

    placeholder: str = "?"
    supports_returning: bool = True

    def quote(self, name: str) -> str:
        """Quote an identifier using SQLite double quotes."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def type_to_sql(self, field_meta: FieldMetadata) -> str:
        """Map a field metadata type to a SQLite SQL type."""
        if field_meta.database.storage_type is not None:
            return str(field_meta.database.storage_type)

        if (
            field_meta.primary_key
            and field_meta.identity_kind == IdentityKind.INTEGER
            and field_meta.generated
        ):
            return "INTEGER PRIMARY KEY AUTOINCREMENT"

        st = field_meta.storage_type
        if isinstance(st, type):
            if issubclass(st, bool):
                return "INTEGER"
            if issubclass(st, int):
                return "INTEGER"
            if issubclass(st, float):
                return "REAL"
            if issubclass(st, (bytes, bytearray)):
                return "BLOB"

        return "TEXT"

    def upsert_sql(
        self,
        table: str,
        conflict_target: tuple[str, ...],
        create_values: dict[str, Any],
        update_values: dict[str, Any],
        returning: tuple[str, ...] | None = None,
    ) -> tuple[str, list[Any]]:
        """Build an upsert SQL statement using ON CONFLICT."""
        cols = list(create_values.keys())
        col_names = ", ".join(self.quote(c) for c in cols)
        val_placeholders = ", ".join(self.placeholder for _ in cols)
        params: list[Any] = [create_values[c] for c in cols]

        conflict_cols = ", ".join(self.quote(c) for c in conflict_target)
        set_clauses: list[str] = []
        for c in update_values:
            set_clauses.append(f"{self.quote(c)} = {self.placeholder}")
            params.append(update_values[c])

        sql = f"INSERT INTO {table} ({col_names}) VALUES ({val_placeholders}) "
        if conflict_target and set_clauses:
            sql += f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {', '.join(set_clauses)}"
        elif conflict_target:
            sql += f"ON CONFLICT ({conflict_cols}) DO NOTHING"

        sql += self.returning_clause(returning)
        return sql, params
