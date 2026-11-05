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

    def index_field_sql(self, field_path: str) -> str:
        """Render a scalar or JSON path as a SQLite index expression."""
        parts = field_path.split(".")
        if len(parts) == 1:
            return self.quote(field_path)
        json_path = "$" + "".join(
            f"[{int(part)}]" if part.isdigit() else f".{part}"
            for part in parts[1:]
        )
        escaped_path = json_path.replace("'", "''")
        return f"json_extract({self.quote(parts[0])}, '{escaped_path}')"

    def type_to_sql(self, field_meta: FieldMetadata) -> str:
        """Map a field metadata type to a SQLite SQL type."""

        if (
            field_meta.primary_key
            and field_meta.database.auto_inc
            and field_meta.generated
        ):
            return "INTEGER PRIMARY KEY AUTOINCREMENT"

        st = field_meta.storage_type
        if st is str:
            max_length = self._max_text_length(field_meta)
            if max_length is not None and max_length <= 255:
                return f"VARCHAR({max_length})"
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

