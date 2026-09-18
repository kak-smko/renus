# Database & Repositories

A `Repository` is the model-specific entry point for persistence and database operations. It binds one model to one database connection and provides model creation, updates, deletion, upserts, queries, counts, and existence checks.


## 1. Create a database and repository

Create a `Database` with an adapter, connect it, and create the model schema before using a repository:

```python
from renus.db import Database, Model, SQLiteAdapter


class User(Model):
    username: str
    name: str


async def example() -> None:
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([User])

    users = db.repository(User)
    await db.disconnect()
```

`db.repository(User)` uses the `primary` connection. With named adapters, select a connection explicitly:

```python
users = db.repository(User, connection="analytics")
```

A repository can also be constructed with an adapter directly:

```python
from renus.db import Repository, SQLiteAdapter


users = Repository(SQLiteAdapter({"database": ":memory:"}), User)
```

The `Database` form is usually preferable because it keeps connection selection and plugins in one place. See [`/docs/database/overview.md`](overview.md) for connection lifecycle and adapter registration.

## 2. Insert models

### `create`

`create(model)` inserts one model and returns the same instance. Generated primary keys and other generated values are copied back to the instance when the adapter returns them.

```python
user = await users.create(User(username="ada", name="Ada Lovelace"))
print(user.username)
print(user.is_persisted())
```

### `create_many`

`create_many(models)` inserts an iterable of models in one bulk operation and returns a list. An empty iterable returns an empty list.

```python
created = await users.create_many(
    [
        User(username="grace", name="Grace Hopper"),
        User(username="alan", name="Alan Turing"),
    ]
)
```

The returned and supplied model objects are marked as persisted. Adapters may return generated values for each inserted row.

## 3. Insert or update with `save`

`save(model)` chooses the operation from the model lifecycle:

- a new model is inserted;
- a persisted, unchanged model is returned without a database write;
- a persisted, dirty model is updated using its dirty fields.

```python
user = User(username="margaret", name="Margaret Hamilton")
await users.save(user)       # insert

user.name = "Margaret H. Hamilton"
await users.save(user)       # update changed fields
```

After a successful save, the model is marked persisted and is no longer dirty. Model lifecycle and dirty-field inspection are covered in [`/docs/database/models.md`](models.md).

## 4. Query from a repository

Use `query()` or its alias `where()` to create a query builder:

```python
active = users.where(User.name.is_not_null())

matching = await active.all()
first = await active.first()
number = await active.count()
present = await active.exists()
```

Both methods accept initial conditions:

```python
user = await users.query(User.username == "ada").first()
```

For filtering, ordering, projections, pagination, relationship loading, aggregates, and query-side mutations, see [`/docs/database/queries.md`](queries.md).

## 5. Direct repository checks

`count(*conditions)` and `exists(*conditions)` are shortcuts for starting a query:

```python
number_of_active = await users.count(User.name.is_not_null())
has_ada = await users.exists(User.username == "ada")
```

With no conditions, they inspect all rows visible to the normal query scope. Soft-deleted rows are excluded by default when the model enables soft deletion; use `with_deleted()` or `only_deleted()` on a query to change that scope. See [`/docs/database/models.md`](models.md) for model soft-delete configuration and [`/docs/database/queries.md`](queries.md) for the query methods.

## 6. Update rows

Use `update()` when the operation should affect at most one matching row, and `update_many()` for a bulk update. Both return the number of affected rows.

```python
one = await users.update(
    User.username == "ada",
    values={"name": "Ada Lovelace"},
)

many = await users.update_many(
    User.name.is_not_null(),
    values={"name": "Verified"},
)
```

The values can also be passed as the final positional argument:

```python
await users.update(User.username == "ada", {"name": "Ada"})
```

Use `save()` when you already have a model instance and want dirty-field tracking. Use repository updates when you want to change database rows directly without first loading models.

## 7. Delete rows

`delete()` accepts either a model instance or conditions:

```python
user = await users.where(User.username == "ada").first()
if user is not None:
    await users.delete(user)

await users.delete(User.username == "grace")
```

The condition form affects at most one matching row. Use `delete_many()` to affect every matching row:

```python
removed = await users.delete_many(User.name.is_not_null())
```

When the model enables soft deletion, `delete()` and `delete_many()` set the deletion fields instead of physically removing rows. Use `hard_delete()` or `hard_delete_many()` to remove rows physically:

```python
await users.hard_delete(User.username == "old-user")
await users.hard_delete_many(User.name.is_null())
```

The methods return the number of affected rows. Relationship cascade behavior depends on the model relationship configuration; see [`/docs/database/models.md`](models.md).

## 8. Upsert rows

`upsert()` inserts a row and updates it when the conflict target already exists. The explicit form requires the fields used for conflict detection, insert values, and update values:

```python
rows = await users.upsert(
    conflict_target=("username",),
    create_values={
        "username": "ada",
        "name": "Ada Lovelace",
    },
    update_values={"name": "Ada Byron Lovelace"},
)
```

For a model instance, pass `target` and let the model primary key be the default conflict target:

```python
user = User(username="ada", name="Ada Lovelace")
await users.upsert(target=user)
```

A query can also express an equality-based conflict target:

```python
await users.where(User.username == "ada").upsert(
    {"name": "Ada Byron Lovelace"}
)
```

The query form uses equality conditions as the conflict target and includes those values when inserting. The result is the number of rows affected.

## 9. Connection and transaction boundaries

Repository methods use the adapter selected at construction time. They do not open or close the `Database` for you, so connect before schema and repository work and disconnect when the application is finished.

For several repository operations that must commit or roll back together, use [`/docs/database/transactions.md`](transactions.md) or [`/docs/database/uow.md`](uow.md):

```python
async with db.transaction():
    await users.create(User(username="katherine", name="Katherine Johnson"))
    await posts.create(Post(title="Programming"))
```

## 10. What repository methods return

| Method | Result |
| --- | --- |
| `create(model)` | The inserted model instance |
| `create_many(models)` | A list of inserted model instances |
| `save(model)` | The inserted or updated model instance |
| `update(...)` | Affected-row count; single-row operation |
| `update_many(...)` | Affected-row count; bulk operation |
| `delete(...)` | Affected-row count; model or single matching row |
| `delete_many(...)` | Affected-row count; all matching rows |
| `hard_delete(...)` | Affected-row count; physical deletion |
| `hard_delete_many(...)` | Affected-row count; physical bulk deletion |
| `upsert(...)` | Affected-row count |
| `count(...)` | Matching-row count |
| `exists(...)` | `True` if at least one row matches |
| `query()` / `where()` | An immutable `Query` builder |

## Next steps

- [`/docs/database/queries.md`](queries.md) — build and execute reads and query-side writes.
- [`/docs/database/mutations.md`](mutations.md) — understand insert, update, delete, and upsert operations in detail.
- [`/docs/database/adapters.md`](adapters.md) — choose and configure a backend.
- [`/docs/database/transactions.md`](transactions.md) — control commit and rollback.
