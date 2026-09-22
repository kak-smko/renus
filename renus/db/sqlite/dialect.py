from __future__ import annotations


from renus.db.core.state import IdentityKind
from renus.db.metadata.core import FieldMetadata
from renus.db.sql.dialect.base import SQLDialect

class SQLiteDialect(SQLDialect):

    placeholder: str = "?"

    def quote(self, name: str) -> str:
        """Quote an identifier using SQLite double quotes."""
        escaped = name.replace('"', '""')
        return f'"{escaped}"'

    def type_to_sql(self, field_meta: FieldMetadata) -> str:
        """Map a field metadata type to a SQLite SQL type."""

        if (
            field_meta.primary_key
            and field_meta.database.auto_inc
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

