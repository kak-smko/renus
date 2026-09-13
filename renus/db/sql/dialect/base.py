from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from renus.db.metadata.core import FieldMetadata

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
