# Database Backup & Restore

Backups are JSON data exports, not schema snapshots. This example assumes `app.sqlite` already contains a `users` table created by your application or migrations. Save it as `backup.py`:

```python
import asyncio
import sys

from renus.db import Database, SQLiteAdapter


async def main() -> None:
    async with Database(SQLiteAdapter({"database": "app.sqlite"})) as db:
        if len(sys.argv) > 1 and sys.argv[1] == "restore":
            counts = await db.restore(
                path="backups/users",
                tables=["users"],
                drop_existing=True,
            )
            print("Restored:", counts)
        else:
            counts = await db.backup(
                path="backups/users",
                tables=["users"],
            )
            print("Backed up:", counts)


if __name__ == "__main__":
    asyncio.run(main())
```

Create a backup with `python backup.py`. Restore it with `python backup.py restore`. Before restoring, make sure the destination database has the compatible schema. **Restore replaces the rows in each selected table by default**; use `drop_existing=False` only when appending is intended. Protect backup files because Renus does not encrypt them, and test restores against an isolated database before relying on them for recovery.

See [Backup & Restore](../database/backup.md) for formats, paging, and restore options.
