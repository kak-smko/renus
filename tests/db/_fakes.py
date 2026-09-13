from __future__ import annotations

from typing import Any

from renus.db.core.exceptions import UnsupportedOperationError

class DDLFakeMixin:

    async def create_schema(self, models: Any) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support create_schema"
        )

    async def ensure_migration_schema(
        self,
        table_name: str = "_db_migrations",
    ) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support migrations"
        )

    async def get_applied_migrations(
        self,
        table_name: str = "_db_migrations",
    ) -> list[dict[str, Any]]:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support migrations"
        )

    async def record_migration(
        self,
        version: str,
        name: str,
        checksum: str,
        applied_at: str,
        table_name: str = "_db_migrations",
    ) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support migrations"
        )

    async def remove_migration(
        self,
        version: str,
        table_name: str = "_db_migrations",
    ) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support migrations"
        )

    async def create_table(
        self,
        name: str,
        columns: Any,
        if_not_exists: bool = True,
    ) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support create_table"
        )

    async def drop_table(
        self,
        name: str,
        if_exists: bool = True,
    ) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support drop_table"
        )

    async def add_column(self, table: str, column: Any) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support add_column"
        )

    async def drop_column(self, table: str, column_name: str) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support drop_column"
        )

    async def rename_column(
        self,
        table: str,
        old_name: str,
        new_name: str,
    ) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support rename_column"
        )

    async def rename_table(self, old_name: str, new_name: str) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support rename_table"
        )

    async def create_index(
        self,
        table: str,
        fields: tuple[str, ...] | list[str],
        unique: bool = False,
        name: str | None = None,
    ) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support create_index"
        )

    async def drop_index(self, table: str, name: str) -> None:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support drop_index"
        )

    async def tables(self) -> list[str]:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support introspection"
        )

    async def backup(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        page_size: int | None = None,
    ) -> dict[str, int]:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support backup"
        )

    async def restore(
        self,
        path: str = "./db",
        tables: list[str] | None = None,
        drop_existing: bool = True,
        chunk_size: int | None = None,
    ) -> dict[str, int]:
        raise UnsupportedOperationError(
            f"adapter {type(self).__name__} does not support restore"
        )
