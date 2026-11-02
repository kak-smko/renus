from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from renus.datastructures.id import ID
from renus.db.metadata.core import FieldMetadata
from renus.db.sql.dialect.base import SQLDialect


class MySQLDialect(SQLDialect):

    placeholder: str = "%s"

    def column_default_sql(self, field_meta: FieldMetadata, type_def: str) -> str:
        if type_def.split("(", 1)[0].upper() in {"TEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT", "BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB", "JSON"}:
            return ""
        return super().column_default_sql(field_meta, type_def)

    def quote(self, name: str) -> str:
        """Quote an identifier using MySQL backticks."""
        escaped = name.replace("`", "``")
        return f"`{escaped}`"

    def limit_offset(
        self,
        sql: str,
        limit: int | None,
        offset: int | None,
    ) -> str:
        """Append a MySQL-compatible LIMIT/OFFSET clause."""
        if limit is None and offset is not None:
            return f"{sql} LIMIT 18446744073709551615 OFFSET {int(offset)}"
        return super().limit_offset(sql, limit, offset)

    def encode_value(self, value: Any, field_meta: Any = None) -> Any:
        """Store timezone-aware datetimes as UTC in MySQL DATETIME columns."""
        if isinstance(value, datetime) and value.utcoffset() is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return super().encode_value(value, field_meta)

    def decode_value(self, value: Any, field_meta: Any = None) -> Any:
        """Decode MySQL temporal values into the field's declared Python type."""
        decoded = super().decode_value(value, field_meta)
        storage_type = getattr(field_meta, "storage_type", None)
        if isinstance(decoded, timedelta) and storage_type is time:
            total_microseconds = (
                decoded.days * 86_400_000_000
                + decoded.seconds * 1_000_000
                + decoded.microseconds
            )
            if 0 <= total_microseconds < 86_400_000_000:
                hours, remainder = divmod(total_microseconds, 3_600_000_000)
                minutes, remainder = divmod(remainder, 60_000_000)
                seconds, microseconds = divmod(remainder, 1_000_000)
                return time(
                    int(hours), int(minutes), int(seconds), int(microseconds)
                )
        if (
            isinstance(decoded, datetime)
            and decoded.tzinfo is None
            and storage_type is datetime
        ):
            return decoded.replace(tzinfo=UTC)
        return decoded

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
            if (
                field_meta.primary_key
                or field_meta.unique
                or field_meta.has_default
                or field_meta.indexed
                or field_meta.foreign_key
            ):
                return "VARCHAR(255)"
        if st in (dict, list):
            return "JSON"
        if isinstance(st, type):
            if issubclass(st, bool):
                return "BOOLEAN"
            if issubclass(st, int):
                return "INT"
            if issubclass(st, float):
                return "DOUBLE"
            if issubclass(st, (bytes, bytearray)):
                return "LONGBLOB"
            if issubclass(st, datetime):
                return "DATETIME(6)"
            if issubclass(st, date):
                return "DATE"
            if issubclass(st, time):
                return "TIME(6)"

        type_name = str(field_meta.inferred_type).lower()
        storage_type = field_meta.storage_type
        if isinstance(storage_type, type) and issubclass(storage_type, ID):
            return "VARCHAR(255)"
        if "datetime" in type_name:
            return "DATETIME(6)"
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

