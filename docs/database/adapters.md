# Adapters

An adapter connects Renus's database API to a concrete backend. The `Database` facade delegates connection management, query execution, mutations, schema operations, transactions, migrations, and backup/restore to the selected adapter.

Renus includes three built-in adapters:

| Adapter | Name | Driver/package | Storage model |
| --- | --- | --- | --- |
| `SQLiteAdapter` | `sqlite` | Python `sqlite3` | SQL tables |
| `MySQLAdapter` | `mysql` | `aiomysql` | SQL tables |
| `MongoDBAdapter` | `mongodb` | async PyMongo | MongoDB collections/documents |

Adapters are selected by a `Database` connection. Repositories and query builders use the selected adapter without changing their public API.

## 1. Choose an adapter

Pass an adapter instance directly to `Database`:

```python
from renus.db import Database, SQLiteAdapter


db = Database(SQLiteAdapter({"database": "storage/app.sqlite"}))
```

The adapter is used as the `primary` connection. You can register several named connections:

```python
from renus.db import Database, SQLiteAdapter


db = Database(
    adapters={
        "primary": SQLiteAdapter({"database": "storage/app.sqlite"}),
        "analytics": SQLiteAdapter({"database": "storage/analytics.sqlite"}),
    }
)

primary_users = db.repository(User)
analytics_users = db.repository(User, connection="analytics")
```

You can also register or replace a connection after constructing the database:

```python
db.register_adapter(
    "reports",
    SQLiteAdapter({"database": "storage/reports.sqlite"}),
)
```

`db.adapter(name)` returns the adapter for a connection and raises `ConfigurationError` when the name is not registered.

## 2. SQLite

SQLite uses the standard-library `sqlite3` module and requires no Renus database extra:

```python
from renus.db import SQLiteAdapter


adapter = SQLiteAdapter(
    {
        "database": "storage/app.sqlite",
        "timeout": 5.0,
        "busy_timeout": 5000,
        "retries": 3,
        "retry_delay": 0.5,
        "journal_mode": "WAL",
    }
)
```

Configuration keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `database` | `":memory:"` | SQLite file path or in-memory database |
| `uri` | value of `database` | Alternative database-path key |
| `timeout` | `5.0` | SQLite connection timeout in seconds |
| `busy_timeout` | `5000` | SQLite busy timeout in milliseconds |
| `retries` | `3` | Connection attempts |
| `retry_delay` | `0.5` | Initial retry delay in seconds; retries use backoff |
| `journal_mode` | `WAL` for file databases | SQLite journal mode |

For a file database, the adapter enables foreign keys, uses WAL mode by default, and sets synchronous mode to `NORMAL`. For `:memory:` databases, the default journal-mode setup is not applied.

SQLite uses `?` parameter placeholders and double-quoted identifiers. Generated integer primary keys use SQLite auto-increment behavior when the model field requests `primary_key=True`, `generated=True`, and `auto_inc=True`.

## 3. MySQL

Install the MySQL extra before using `MySQLAdapter`:

```bash
pip install "renus[mysql]"
```

Configure the adapter with connection and pool settings:

```python
from renus.db import MySQLAdapter


adapter = MySQLAdapter(
    {
        "host": "localhost",
        "port": 3306,
        "username": "app",
        "password": "secret",
        "database": "app_db",
        "min_pool": 5,
        "max_pool": 100,
        "connect_timeout": 5,
        "retries": 3,
        "retry_delay": 0.5,
    }
)
```

Configuration keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `host` | `localhost` | MySQL server host |
| `port` | `3306` | MySQL server port |
| `username` or `user` | `root` | Login user |
| `password` | empty string | Login password |
| `database` or `db` | `db` | Database name |
| `min_pool` or `minsize` | `5` | Minimum pool size |
| `max_pool` or `maxsize` | `100` | Maximum pool size |
| `connect_timeout` | `5` | Connection timeout |
| `retries` | `3` | Connection attempts |
| `retry_delay` | `0.5` | Initial retry delay in seconds; retries use backoff |

The adapter creates an `aiomysql` pool with `autocommit=False`. Standalone mutations commit after execution; mutations inside an active transaction use that transaction's connection. MySQL uses `%s` parameter placeholders and backtick-quoted identifiers.

## 4. MongoDB

Install the MongoDB extra before using `MongoDBAdapter`:

```bash
pip install "renus[mongo]"
```

Configure the URI and database name:

```python
from renus.db import MongoDBAdapter


adapter = MongoDBAdapter(
    {
        "uri": "mongodb://localhost:27017",
        "database": "app_db",
        "min_pool": 0,
        "max_pool": 100,
        "server_selection_timeout_ms": 5000,
        "connect_timeout_ms": 20000,
        "retries": 3,
        "retry_delay": 0.5,
    }
)
```

Configuration keys:

| Key | Default | Meaning |
| --- | --- | --- |
| `uri` | `mongodb://localhost:27017` | MongoDB connection URI |
| `database` | `db` | Database name |
| `username` | unset | Optional username |
| `password` | unset | Optional password |
| `min_pool` | `0` | Minimum connection pool size |
| `max_pool` | `100` | Maximum connection pool size |
| `server_selection_timeout_ms` | `5000` | Server selection timeout |
| `connect_timeout_ms` | `20000` | Connection timeout |
| `socket_timeout_ms` | unset | Optional socket timeout |
| `retries` | `3` | Connection attempts |
| `retry_delay` | `0.5` | Initial retry delay in seconds; retries use backoff |

MongoDB uses native async PyMongo access and stores model fields in collections, including nested model and JSON fields as native BSON values. When an integer auto-increment field is requested, it allocates values through the internal `__counters__` collection. A model's `id` primary key maps to MongoDB's `_id` storage field;


## 5. Common adapter lifecycle

Connect explicitly:

```python
await db.connect()

healthy = await db.health_check()
print(healthy)

await db.disconnect()
```

`connect()` and `disconnect()` without a connection name operate on all registered adapters. Pass a name to operate on one connection:

```python
await db.connect("analytics")
await db.disconnect("analytics")
```

The `Database` object is also an async context manager:

```python
async with Database(SQLiteAdapter({"database": ":memory:"})) as db:
    print(await db.health_check())
```

Adapters also expose schema creation through `db.create_schema(models)`. Use migrations for changes to an existing schema; see [`/docs/database/migrations.md`](migrations.md).

## 6. The adapter contract

Custom adapters implement `AsyncDatabaseAdapter`. The required operations are:

### Connection and execution

```python
from typing import Any
from renus.db import AsyncDatabaseAdapter, CompiledMutation, CompiledQuery


class ExampleAdapter(AsyncDatabaseAdapter):
    name = "example"

    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    async def execute_query(self, compiled: CompiledQuery[Any]):
        ...

    async def execute_mutation(self, compiled: CompiledMutation):
        ...

    def transaction_factory(self):
        ...

    async def health_check(self) -> bool:
        ...
```

`execute_query()` returns an iterable of row-like values. `execute_mutation()` returns `MutationResult`:

```python
from renus.db import MutationResult


MutationResult(
    rows_affected=1,
    last_id=42,
    generated={"id": 42},
)
```

`rows_affected` is the direct mutation count. `last_id` can carry a single generated identifier, and `generated` can carry generated field values or per-row values for bulk inserts.

### Schema and operational methods

An adapter must also implement methods for:

- `create_schema(models)`;
- migration tracking: `ensure_migration_schema()`, `get_applied_migrations()`, `record_migration()`, and `remove_migration()`;
- DDL: `create_table()`, `drop_table()`, `add_column()`, `drop_column()`, `rename_column()`, `rename_table()`, `create_index()`, and `drop_index()`;
- `tables()`;
- `backup()` and `restore()`.

The exact storage implementation is backend-specific, but the `Database` facade uses these methods consistently.

## 7. Compilation and portability

Repositories create model-neutral query and mutation structures. SQL adapters use a SQL dialect and compiler; MongoDB uses its own compiler. This separation handles differences such as:

- SQL tables versus MongoDB collections;
- SQL placeholders (`?` for SQLite and `%s` for MySQL);
- quoted SQL identifiers versus document paths;

- SQL JSON column storage versus native nested MongoDB values.

Use the repository and query APIs for portable application code. Use adapter-specific features only when the selected backend is intentional.

## 8. Transactions

All built-in adapters provide transaction contexts. Use the database facade:

```python
async with db.transaction():
    await db.repository(User).create(User(username="one"))
    await db.repository(User).create(User(username="two"))
```

The built-in adapters reject nested transactions. Commit and rollback behavior is described in [`/docs/database/transactions.md`](transactions.md).

## 9. Register custom adapters

Register a class or adapter instance under a case-insensitive name:

```python
from renus.db import AsyncDatabaseAdapter, register_adapter


class SearchDatabaseAdapter(AsyncDatabaseAdapter):
    name = "search"
    # implement the adapter contract
    ...


register_adapter("search", SearchDatabaseAdapter)
```

The registry accepts an `AsyncDatabaseAdapter` instance or a subclass. Resolve a registered adapter with `get_adapter("search")` and check availability with `has_adapter("search")`.

Adapters can also be discovered from the `db.adapters` and `renus.db.adapters` entry-point groups. A module path in the form `package.module:AdapterClass` can be resolved by `get_adapter()`.

Once registered, a `Database` can resolve the adapter through its configuration:

```python
from renus.config import Config


# The database configuration may provide an adapter instance, a factory,
# a registered driver name, or a module path supported by the registry.
```

The exact configuration file loading rules belong to Renus configuration; the database facade checks connection-specific adapter settings first, then the generic database adapter/driver setting. See [`/docs/database/overview.md`](overview.md) for the facade-level setup.

## Next steps

- [`/docs/database/repositories.md`](repositories.md) — use one adapter through repositories.
- [`/docs/database/queries.md`](queries.md) — build backend-neutral reads.
- [`/docs/database/mutations.md`](mutations.md) — execute backend-neutral writes.
- [`/docs/database/migrations.md`](migrations.md) — evolve schemas.
- [`/docs/database/backup.md`](backup.md) — back up and restore data.
