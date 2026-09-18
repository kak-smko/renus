# Migrations

Migrations are versioned Python files that change an existing database schema. Renus discovers the files in a migration directory, runs their `upgrade(adapter)` or `downgrade(adapter)` function, and records applied versions in the `_db_migrations` table.

Use migrations after the initial schema has been created. `db.create_schema(models)` is covered in [`/docs/database/overview.md`](/docs/database/overview.md); migrations are for controlled changes to an existing schema.

## Create a migration manager

Bind a manager to a `Database` and a directory:

```python
migrations = db.migration_manager(path="migrations")
```

The default directory is `migrations`, and the default connection is `primary`. For another registered connection:

```python
migrations = db.migration_manager(
    path="migrations/analytics",
    connection="analytics",
)
```

Connect the database before applying or inspecting migrations:

```python
async with db:
    migrations = db.migration_manager(path="migrations")
    await migrations.upgrade()
```

## Migration file format

Migration files are `.py` files whose names normally contain a version and a description, for example `0001_create_accounts.py`:

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

Each migration must define `upgrade` and `downgrade`. Renus passes the selected database adapter to a function that accepts an argument. Synchronous functions are also supported, although asynchronous functions are the normal form.

The migration manager discovers non-hidden `.py` files in sorted filename order. The version is the complete filename stem (`0001_create_accounts`), and the name is the part after the first underscore (`create_accounts`). Files beginning with `__` or `.` are ignored.

## Scaffold a file

Call `create(name)` to create the next numbered migration file:

```python
path = migrations.create("add audit to accounts")
print(path)
# migrations/0002_add_audit_to_accounts.py
```

The generated file imports `Column` and contains empty async `upgrade` and `downgrade` functions. Edit the file before applying it.

## Schema operations

Migration functions receive an adapter, so schema changes use adapter DDL methods:

```python
from renus.db.migrations import Column


async def upgrade(adapter) -> None:
    await adapter.add_column("accounts", Column("status", "str", default="open"))
    await adapter.create_index("accounts", ["owner"], name="idx_accounts_owner")


async def downgrade(adapter) -> None:
    await adapter.drop_index("accounts", "idx_accounts_owner")
    await adapter.drop_column("accounts", "status")
```

Available adapter schema methods include:

- `create_table(name, columns, if_not_exists=True)`;
- `drop_table(name, if_exists=True)`;
- `add_column(table, column)`;
- `drop_column(table, column_name)`;
- `rename_column(table, old_name, new_name)`;
- `rename_table(old_name, new_name)`;
- `create_index(table, fields, unique=False, name=None)`;
- `drop_index(table, name)`.

`Column` accepts `name`, `type`, `nullable`, `primary_key`, `generated`, `unique`, `default`, `foreign_key`, `on_delete`, `on_update`, and `comment`. Backend support for a particular DDL operation follows the selected adapter.

## Apply migrations

Apply all pending migrations with `upgrade()`:

```python
applied = await migrations.upgrade()
print(applied)
# ['0001_create_accounts', '0002_add_audit_to_accounts']
```

Each non-fake upgrade runs inside a transaction. The migration is recorded only after its `upgrade` function succeeds. If the upgrade raises an exception, its schema changes and tracking record are rolled back when the backend supports the transaction boundary.

Stop after a target version by passing its full version or a matching prefix:

```python
await migrations.upgrade(target="0002")
```

Use `fake=True` when the database already has the intended change and only the tracking record should be written:

```python
await migrations.upgrade(target="0002", fake=True)
```

A fake migration does not execute `upgrade(adapter)`.

## Inspect migration status

`status()` returns a `MigrationStatus` for every discovered file:

```python
for migration in await migrations.status():
    print(
        migration.version,
        migration.applied,
        migration.applied_at,
        migration.file_path,
    )
```

Each status contains `version`, `name`, `applied`, `applied_at`, `checksum`, and `file_path`. The checksum is the SHA-256 digest of the migration file currently on disk.

Use `check()` to verify that applied migration files have not changed:

```python
assert await migrations.check() is True
```

If an applied file's contents differ from its recorded checksum, Renus raises `MigrationChecksumError` during `check()` and before `upgrade()` applies pending files. Restore the original file or deliberately handle the migration history before continuing; do not edit an already-applied migration as a normal schema-change workflow.

## Revert migrations

`downgrade()` reverts the most recently applied migration by default:

```python
reverted = await migrations.downgrade()
```

Other targets:

```python
await migrations.downgrade(2)          # revert two applied migrations
await migrations.downgrade("0002")     # revert migrations after 0002
await migrations.downgrade("base")     # revert all applied migrations
await migrations.downgrade("0")        # same as base
```

The downgrade functions run in reverse application order. A normal downgrade removes the tracking record after its `downgrade` function succeeds. `fake=True` removes the tracking record without executing the downgrade:

```python
await migrations.downgrade("0002", fake=True)
```

`reset()` is an alias for reverting all applied migrations:

```python
await migrations.reset()
```

## Tracking and ordering

Renus creates `_db_migrations` when migration state is read or written. Each record stores:

- `version`;
- `name`;
- `applied_at` as an ISO timestamp;
- `checksum` as a SHA-256 hex digest.

Applied migrations are ordered by version. Migration versions are strings derived from filenames, so use a consistent sortable naming scheme such as `0001_`, `0002_`, and so on.

## Errors

Migration operations can raise:

- `MigrationError` when a migration cannot be loaded or does not define the requested function;
- `MigrationChecksumError` when an applied file was modified;
- `MigrationNotFoundError` when a recorded migration file is missing during downgrade.

Import these exceptions from `renus.db.migrations` when an application needs to handle them explicitly:

```python
from renus.db.migrations import MigrationChecksumError, MigrationError
```

