# Database Configuration

Renus database settings live in the project’s `config.database` module. This page describes automatic database construction and the settings it reads. For backend connection options, see [Adapters](../database/adapters.md).

## Configure a single adapter

When `Database()` is constructed without an explicit adapter, it reads the `database` configuration and resolves an adapter for the primary connection. The framework accepts a database adapter instance, a zero-argument factory returning an adapter, or a registered driver name.

A direct adapter instance or factory can be configured from Python:

```python
# config/database.py
from renus.db import SQLiteAdapter

adapter = SQLiteAdapter({"database": "storage/app.sqlite"})
```

Then:

```python
from renus.db import Database

db = Database()  # resolves the configured primary adapter
```

Or select a built-in driver by name and place the adapter’s connection options at the module’s top level:

```python
# config/database.py
driver = "sqlite"
database = "storage/app.sqlite"
timeout = 5.0
```

The built-in driver names are `sqlite`, `mysql`, and `mongodb`. Additional adapters can be registered, exposed through the `db.adapters` or `renus.db.adapters` Python entry-point group, or referenced by an import path in the form `package.module:AdapterClass`. The adapter registry requires an `AsyncDatabaseAdapter` instance or subclass.

For driver-name configuration, `Database` passes the resolved adapter factory no settings; the adapter instance must be configured separately. The database CLI’s `get_database()` path assigns the `Config("database")` object as the adapter’s config. For the most predictable behavior across `Database()` and CLI commands, construct an adapter instance with its explicit settings or use the database CLI’s documented top-level settings convention.

## Select a connection

`Database` resolves the primary connection using the first truthy value it finds in this order:

1. `primary.adapter`
2. `connections.primary.adapter`
3. `adapter`
4. `primary.driver`
5. `connections.primary.driver`
6. `driver`

The value may be an adapter instance, a zero-argument callable factory, or a driver name. A driver name is looked up in the adapter registry. An unresolved or invalid adapter raises `ConfigurationError`.

Although `Database._resolve_adapter_from_config()` checks the per-connection paths above, `Database()` only resolves the `primary` connection automatically. Use the `adapters` argument for additional named connections:

```python
from renus.db import Database, SQLiteAdapter

db = Database(
    adapters={
        "primary": SQLiteAdapter({"database": "storage/app.sqlite"}),
        "analytics": SQLiteAdapter({"database": "storage/analytics.sqlite"}),
    }
)

users = db.repository(User)  # primary
reports = db.repository(Report, connection="analytics")
```

`Database.connect()` and `.disconnect()` manage all registered adapters by default; pass a connection name to manage only one. See [Database Overview](../database/overview.md) for lifecycle and repository examples.

## Database CLI configuration

The `renus db` commands use top-level settings from `Config("database")`. `driver` selects the backend; if omitted, the CLI infers MongoDB from a `uri` beginning with `mongodb`, SQLite when `database` is set without a URI, and otherwise defaults to MongoDB. Adapter-specific settings are read from the same config object.

For example, a SQLite config for the CLI looks like:

```python
# config/database.py
driver = "sqlite"
database = "storage/app.sqlite"
timeout = 5.0
busy_timeout = 5000
retries = 3
retry_delay = 0.5
```

Use `driver = "mysql"` or `driver = "mongodb"` and provide that adapter’s options instead. Install the matching extra (`renus[mysql]` or `renus[mongo]`) before connecting. See [Database Commands](../cli/db.md) and [Adapters](../database/adapters.md) for commands and full backend option tables.

## Identity type

The optional `ID` setting controls the concrete value used by the `ID` field annotation. It defaults to `int`:

```python
# config/database.py
from uuid import UUID, uuid4

ID = UUID
```

The configured type must support the identity-generation behavior required by your models. For integer IDs, the database can generate auto-increment values. MongoDB auto-increment fields require `ID = int`; see [ID](../database/id.md) for identity-specific details.
