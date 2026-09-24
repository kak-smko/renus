from __future__ import annotations


from renus.db.metadata.core import FieldMetadata
from renus.db.sql.dialect.base import SQLDialect


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
        if st is str:
            max_length = self._max_text_length(field_meta)
            if max_length is not None and max_length <= 255:
                return f"VARCHAR({max_length})"
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

        return "LONGTEXT"

