# Database Migrations

A migration changes an existing schema and records that change in `_db_migrations`. Keep the migration file and the runner separate.

Create `migrations/0001_create_accounts.py`:

```python
from renus.db.migrations import Column


async def upgrade(adapter) -> None:
    await adapter.create_table(
        "accounts",
        [
            Column("id", "str", primary_key=True),
            Column("owner", "str", nullable=False),
            Column("balance", "float", default=0.0),
        ],
    )


async def downgrade(adapter) -> None:
    await adapter.drop_table("accounts")
```

Create `migrate.py`:

```python
import asyncio

from renus.db import Database, SQLiteAdapter


async def main() -> None:
    async with Database(SQLiteAdapter({"database": "app.sqlite"})) as db:
        migrations = db.migration_manager(path="migrations")
        applied = await migrations.upgrade()
        print("Applied:", applied)


if __name__ == "__main__":
    asyncio.run(main())
```

Run `python migrate.py` from the project directory. The database context connects before the migration runs. On the first run, `0001_create_accounts` is applied; later runs skip it. Do not edit an applied migration—add a new versioned file for each schema change. Back up important data before migrations and test downgrades against a non-production database.

See [Migrations](../database/migrations.md) for scaffolding, status checks, checksums, and downgrade operations.
