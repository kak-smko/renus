# Backup & Restore

Renus can export user tables or collections to a directory of JSON files and restore those files later. The `Database` facade delegates the operation to the selected adapter.

Backups are data exports, not schema snapshots. They contain rows/documents only; use [`/docs/database/migrations.md`](/docs/database/migrations.md) to create or evolve the schema before restoring data.

## Create a backup

Connect the database, then call `db.backup()`:

```python
counts = await db.backup(path="storage/db-backup")
print(counts)
# {'accounts': 2, 'users': 10}
```

The adapter creates the destination directory if needed. Each selected table is written to `<table>.json` as a JSON array. The returned dictionary contains the number of exported rows/documents for each table.

Back up selected tables with `tables`:

```python
counts = await db.backup(
    path="storage/user-backup",
    tables=["users", "accounts"],
)
```

A backup can use a different registered connection:

```python
counts = await db.backup(
    path="storage/analytics-backup",
    connection="analytics",
)
```

For large tables, `page_size` controls how many records are read and written per page. Its default is `1000`:

```python
counts = await db.backup(
    path="storage/large-backup",
    tables=["events"],
    page_size=5000,
)
```

The output directory for the example above contains files such as:

```text
storage/large-backup/
└── events.json
```

When `tables` is omitted, Renus exports all tables returned by the adapter. The internal `_db_migrations` tracking table is excluded from the adapter's table listing and from automatic restore discovery.

## Backup format

Every table file is a JSON array of objects:

```json
[
  {
    "id": "u1",
    "name": "Ada",
    "created_at": {
      "$date": "2026-01-01T12:00:00Z"
    }
  }
]
```

Renus encodes values that JSON does not represent directly:

| Value | Backup representation |
| --- | --- |
| `datetime` and `date` | `{"$date": ...}` |
| `time` | `{"$time": ...}` |
| `UUID` | `{"$uuid": ...}` |
| `Decimal` | `{"$numberDecimal": ...}` |
| Renus `ID` | `{"$id": ...}` |
| `bytes` and `bytearray` | `{"$binary": {"base64": ..., "subType": "00"}}` |
| enum value | `{"$enum": ...}` |

Nested dictionaries and sequences are encoded recursively. Values that cannot be converted to a JSON-safe representation raise `TypeError` during backup.

The JSON files are portable between the built-in SQL and MongoDB adapters when their stored field values are supported by the backup encoder. Keep backup files protected: they contain application data and are not encrypted by Renus.

## Restore a backup

Restore all JSON files in a directory with:

```python
counts = await db.restore(path="storage/db-backup")
print(counts)
```

Restore selected tables only:

```python
counts = await db.restore(
    path="storage/user-backup",
    tables=["users"],
)
```

By default, `drop_existing=True`. For every table whose backup file exists, Renus removes the current rows/documents before inserting the backup contents. This makes a normal restore replace the selected table data:

```python
counts = await db.restore(
    path="storage/user-backup",
    tables=["users"],
    drop_existing=True,
)
```

Set `drop_existing=False` to keep current data and insert the backup records after it:

```python
counts = await db.restore(
    path="storage/user-backup",
    tables=["users"],
    drop_existing=False,
)
```

The returned dictionary reports the number of restored records per table. A requested table whose JSON file does not exist is skipped. If automatic discovery is requested for a directory that does not exist, restore returns `{}`.

For large backups, `chunk_size` controls the number of records loaded per batch. Its default is `1000`:

```python
counts = await db.restore(
    path="storage/large-backup",
    tables=["events"],
    chunk_size=5000,
)
```

## Full replacement example

The schema must exist before restoring rows. The following replaces the contents of selected tables:

```python
from renus.db import Database, SQLiteAdapter


async def restore_database() -> dict[str, int]:
    async with Database(
        SQLiteAdapter({"database": "storage/app.sqlite"})
    ) as db:
        # The tables must already exist. Create or update them through the
        # normal schema and migration workflow before this call.
        return await db.restore(
            path="storage/db-backup",
            tables=["users", "accounts"],
            drop_existing=True,
        )
```

Restore inserts records using the keys present in each JSON object. It does not recreate tables, indexes, relationships, or migration records. Run the appropriate migrations first and ensure the backup matches that schema.

## API reference

### `Database.backup`

```python
await db.backup(
    path="./db",
    tables=None,
    connection="primary",
    page_size=None,
)
```

Returns `dict[str, int]` with exported row/document counts.

### `Database.restore`

```python
await db.restore(
    path="./db",
    tables=None,
    drop_existing=True,
    connection="primary",
    chunk_size=None,
)
```

Returns `dict[str, int]` with restored row/document counts.

## Operational guidance

- Back up before destructive migrations or data changes.
- Test restoring a backup in an isolated database before relying on it for recovery.
- Store backups outside the application process's temporary directories and restrict access to them.
- Keep the backup and schema versions together so the data can be restored into the expected structure.
- Do not treat a successful row count as proof that relationships or application invariants are valid; validate the restored application state.

See [`/docs/database/adapters.md`](/docs/database/adapters.md) for backend selection and [`/docs/database/overview.md`](/docs/database/overview.md) for database lifecycle setup.
