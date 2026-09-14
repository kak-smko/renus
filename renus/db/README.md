# DB

DB is an **async-only**, database-independent persistence framework for Python 3.11+.
Application code depends on `ReModel`, `Field`, repositories, the query/mutation AST, and Unit of Work—not on SQL or MongoDB APIs.

## Status

The repository contains the complete architecture and adapters for SQLite, MySQL, and MongoDB, with optional driver dependencies. SQLite is runnable without third-party database drivers by using the standard-library SQLite engine behind an async adapter boundary. MySQL and MongoDB require their optional driver extras.

## Quick start

```python
from db import Database, ReModel, Field, DatabaseField

class User(ReModel):
    name: str = Field(max_len=20, database=DatabaseField(nullable=False))
    age: int | None = Field(database=DatabaseField(nullable=True))

    class Meta:
        timestamps = True
        soft_delete = True

# Idiomatic: Database as an async context manager 
async with Database(SQLiteAdapter(":memory:")) as db:
    await db.create_schema([User])
    users = db.repository(User)
    user = users.create(User(name="Ali", age=25))
    user = users.query().where(User.id == user.id).first()
    user.name = "Reza"
    await users.save(user)

# Equivalent classic style: an explicit Database + per-model repository.
db = Database()
await db.connect()
await db.create_schema([User])
users = db.repository(User)

user = await users.create(User(name="Ali", age=25))
user = await users.query(User.id == user.id).first()
user.name = "Reza"
await users.save(user)
```

`User.connect(db)` is a thin convenience for `db.repository(User)`. The same repository and query code is intended to work with `driver: mysql` or `driver: mongodb`.

## Portability levels

**Portable:** CRUD, filtering, ordering, pagination, count/exists, timestamps, soft delete, model serialization and the core repository/UoW contracts.

**Capability-dependent:** transactions, joins, foreign-key enforcement, returning, advanced indexing and backend features exposed through `DatabaseCapabilities`.

**Backend-specific:** native Mongo pipelines, raw SQL, and dialect-specific extensions. These are deliberately outside the portable API.

## Architecture

```text
Application
  -> ReModel / Metadata
  -> Repository
  -> Unit Of Work
  -> Query or Mutation AST
  -> Compiler / Planner
  -> AsyncDatabaseAdapter
  -> Driver
  -> Database
```

Core never imports a database driver. Adapter discovery uses the `db.adapters` Python entry-point group.

## Optional drivers

```bash
pip install -e '.[sqlite]'
pip install -e '.[mysql]'
pip install -e '.[mongodb]'
pip install -e '.[all,dev]'
```

## Migrations

```bash
renus migrate create add_users
renus migrate upgrade
renus migrate downgrade
```

Migrations are deliberately adapter-aware: SQL migrations can issue SQL through a backend extension, while Mongo migrations can transform documents. No claim is made that SQL and Mongo schemas have identical physical semantics.

## Third-party adapter

Implement `AsyncDatabaseAdapter`, expose `DatabaseCapabilities`, compile DB ASTs to your backend's native operations