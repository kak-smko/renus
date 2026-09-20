from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from renus.db.core.adapter import AsyncDatabaseAdapter

MIGRATIONS_TABLE = "_db_migrations"

@dataclass(frozen=True)
class MigrationRecord:
    """Record the application of a single migration."""

    version: str
    name: str
    applied_at: str
    checksum: str

class MigrationTracker:
    """Track applied migrations in a database table."""

    def __init__(
        self,
        adapter: AsyncDatabaseAdapter,
        table_name: str = MIGRATIONS_TABLE,
    ) -> None:
        """Bind the tracker to an adapter.

        Parameters
        ----------
        adapter:
            The database adapter used to persist migration records.
        table_name:
            Name of the tracking table. Defaults to ``"_db_migrations"``.
        """
        self.adapter = adapter
        self.table_name = table_name

    async def ensure_schema(self) -> None:
        """Ensure the tracking table exists."""
        await self.adapter.ensure_migration_schema(self.table_name)

    async def get_applied_migrations(self) -> list[MigrationRecord]:
        """Return the list of applied migrations."""
        raw_records = await self.adapter.get_applied_migrations(self.table_name)
        records = [
            MigrationRecord(
                version=str(r.get("version", "")),
                name=str(r.get("name", "")),
                applied_at=str(r.get("applied_at", "")),
                checksum=str(r.get("checksum", "")),
            )
            for r in raw_records
        ]
        return sorted(records, key=lambda r: r.version)

    async def record_migration(
        self,
        version: str,
        name: str,
        checksum: str,
    ) -> None:
        """Record a migration as applied."""
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.adapter.record_migration(
            version,
            name,
            checksum,
            now_iso,
            table_name=self.table_name,
        )

    async def remove_migration(self, version: str) -> None:
        """Remove a migration record from the tracking table."""
        await self.adapter.remove_migration(version, table_name=self.table_name)
