# Transactions

`db.transaction()` groups database operations on one named connection into an atomic boundary. It is an asynchronous context manager.

Create a transaction from `Database` and use it with `async with`:

```python
async with db.transaction():
    await db.repository(User).create(User(id="u1", name="Ada"))
    await db.repository(Account).create(Account(user_id="u1", balance=100))
```

When the block exits normally, Renus commits the transaction. If an exception escapes the block, Renus rolls it back and re-raises the exception:

```python
try:
    async with db.transaction():
        await db.repository(User).create(User(id="u2", name="Grace"))
        raise RuntimeError("cancel this operation")
except RuntimeError:
    pass

# The User insert was rolled back.
```

You can also keep the transaction context and explicitly control it:

```python
async with db.transaction() as transaction:
    await db.repository(User).create(User(id="u3", name="Katherine"))
    await transaction.commit()
```

The transaction context exposes `commit()` and `rollback()`. A manual rollback prevents the changes from being committed when the context exits.

## Connection selection

The default connection is `primary`. Pass a connection name to both the transaction and the repositories that participate in it:

```python
async with db.transaction("analytics"):
    events = db.repository(Event, connection="analytics")
    await events.create(Event(id="e1", name="signup"))
```

Operations made through another connection do not belong to this transaction.

## Nested transactions

The built-in adapters reject nested transactions. Start one transaction around the complete operation instead of opening another transaction inside it:

```python
async with db.transaction():
    await create_user_and_account()
    # create_user_and_account() should use the active connection;
    # it should not open another db.transaction() block.
```

If an application needs independent transaction boundaries, complete the outer context before starting the next one.


Transactions do not replace the repository and query APIs. See [`/docs/database/repositories.md`](/docs/database/repositories.md), [`/docs/database/mutations.md`](/docs/database/mutations.md), and [`/docs/database/queries.md`](/docs/database/queries.md) for the operations placed inside these boundaries.

## Connection lifecycle

Connect the database before opening a transaction. The database context manager is a convenient way to manage the connection lifecycle:

```python
async with Database(SQLiteAdapter({"database": "storage/app.sqlite"})) as db:
    await db.create_schema([User, Account])

    async with db.transaction():
        await db.repository(User).create(User(id="u6", name="Dorothy"))
```

See [`/docs/database/overview.md`](/docs/database/overview.md) for database setup and [`/docs/database/adapters.md`](/docs/database/adapters.md) for backend-specific connection behavior.
