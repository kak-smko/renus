# Mutations

Mutations change persisted data. Repository methods create immutable mutation descriptions, pass them through the selected adapter, and return the adapter's affected-row result. Mutation methods are asynchronous.


## 1. The write lifecycle

A typical mutation has four steps:

1. Construct or select model values.
2. Build a repository mutation operation.
3. Let the adapter compile and execute it.
4. Inspect the returned model or affected-row count.

```python
from renus.db import Database, Model, SQLiteAdapter


class User(Model):
    username: str
    name: str


async def create_user() -> User:
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([User])

    users = db.repository(User)
    user = await users.create(User(username="ada", name="Ada Lovelace"))
    await db.disconnect()
    return user
```

Each adapter returns a `MutationResult` internally. Repository methods expose the useful parts of that result: generated values are applied to created models, while direct row operations return `rows_affected`.

## 2. Insert one model

Use `create(model)` for one insert:

```python
user = await users.create(
    User(username="grace", name="Grace Hopper")
)
```

The model is converted into insert values from its declared fields. Generated fields that are not set are omitted so the database or adapter can allocate them. After a successful insert, the returned object is marked persisted.

If the adapter returns a generated primary key or other generated values, Renus copies them into fields that were still unset:

```python
user = await users.create(User(username="alan", name="Alan Turing"))
print(user.id)
```

The exact generated identity behavior depends on the model field metadata and configured identity type; see [`/docs/database/id.md`](id.md).

## 3. Insert many models

Use `create_many(models)` for a bulk insert:

```python
created = await users.create_many(
    [
        User(username="katherine", name="Katherine Johnson"),
        User(username="dorothy", name="Dorothy Vaughan"),
    ]
)
```

The method returns the supplied model objects as a list and marks each as persisted. An empty iterable returns `[]` without executing a mutation.

Bulk inserts use one `InsertMany` operation. Adapters that generate IDs in bulk may return one generated value per model; Renus assigns those values to the corresponding objects.

## 4. Save a model

`save(model)` chooses insert or update from the model lifecycle:

```python
user = User(username="margaret", name="Margaret Hamilton")
await users.save(user)       # creates the row

user.name = "Margaret H. Hamilton"
await users.save(user)       # updates dirty fields
```

A new model follows the `create()` path. A persisted and unchanged model produces no write. A dirty persisted model produces an update containing its dirty fields and identity filters.

Use `save()` when the application has a model instance. Use direct update methods when it is more efficient to change rows without hydrating them first.

## 5. Update one matching row

`update()` accepts conditions and a values dictionary and returns the number of affected rows:

```python
rows = await users.update(
    User.username == "ada",
    values={"name": "Ada Byron Lovelace"},
)
```

The operation is single-row: SQL adapters compile it with `LIMIT 1`, and document adapters use a single-document update operation. To update every matching row, use `update_many()`.

The values dictionary may be the final positional argument:

```python
await users.update(User.username == "ada", {"name": "Ada"})
```

Values may use field names or field paths. The mutation normalizes a path to its final field name before compilation. Prefer ordinary model field names for portable writes.

## 6. Update many rows

`update_many()` applies values to all rows matching its conditions:

```python
rows = await users.update_many(
    User.active == True,
    values={"status": "verified"},
)
print(rows)
```

With an explicit `values=` argument, no condition means every row is eligible. Add a condition whenever a global update is not intended.

The method returns `rows_affected`. This is the backend's affected-row count; for some databases, an update that sets a value to its current value may report zero modified rows.

## 7. Delete one model or row

`delete()` accepts either a model instance or a condition:

```python
user = await users.where(User.username == "ada").first()
if user is not None:
    await users.delete(user)

await users.delete(User.username == "grace")
```

The model form builds identity filters from the instance. The condition form is single-row and returns the affected-row count.

## 8. Delete many rows

Use `delete_many()` for every row matching the supplied conditions:

```python
rows = await users.delete_many(User.active == False)
```

When the model has soft deletion enabled, `delete()` and `delete_many()` update its deletion fields instead of issuing a physical delete. Normal queries then hide those rows. See [`/docs/database/queries.md`](queries.md) for `with_deleted()` and `only_deleted()`.

## 9. Hard deletion

`hard_delete()` and `hard_delete_many()` always issue physical deletion operations and ignore the model's soft-delete scope:

```python
await users.hard_delete(User.username == "temporary")
await users.hard_delete_many(User.status == "expired")
```

The model form of `hard_delete()` also uses the model identity. These methods are irreversible at the database layer unless the data is available from a backup.

## 10. Upsert

An upsert inserts a row when its conflict target is absent and updates it when the target already exists.

### Explicit values

```python
rows = await users.upsert(
    conflict_target=("username",),
    create_values={
        "username": "ada",
        "name": "Ada Lovelace",
    },
    update_values={
        "name": "Ada Byron Lovelace",
    },
)
```

The `conflict_target` is an iterable of field names or paths. `create_values` supplies the insert row. `update_values` supplies only the values to change when a conflict is found.

### From a model

Pass `target` to derive insert values from a model. If no conflict target is supplied, Renus uses the model's primary-key fields:

```python
user = User(username="ada", name="Ada Lovelace")
await users.upsert(target=user)
```

A model without metadata or identity requires an explicit conflict target.

### From a query

A query can turn equality filters into an upsert conflict target:

```python
await users.where(User.username == "ada").upsert(
    {"name": "Ada Byron Lovelace"}
)
```

Only equality conditions with a non-`None` value become conflict-target fields. If no such condition exists, the model primary key is used when available; otherwise the operation raises `ValueError`.

## 11. Mutation ASTs and adapters

The public repository methods create these immutable mutation descriptions:

| Mutation | Built by | Purpose |
| --- | --- | --- |
| `Insert` | `create()` | Insert one record |
| `InsertMany` | `create_many()` | Insert multiple records |
| `Update` | `save()` or `update()` | Update one record or model's dirty fields |
| `UpdateMany` | `update_many()` | Bulk update |
| `Delete` | `delete()` or `hard_delete()` | Delete one record or matching row |
| `DeleteMany` | `delete_many()` or `hard_delete_many()` | Bulk delete |
| `Upsert` | `upsert()` | Insert-or-update on conflict |

SQL adapters compile these operations into parameterized SQL. MongoDB compiles them into collection operations such as `insert_one`, `insert_many`, `update_one`, `update_many`, `delete_one`, `delete_many`, and `update_one(..., upsert=True)`. See [`/docs/database/adapters.md`](adapters.md) for backend configuration and the adapter contract.

## 12. Errors and affected rows

Common mutation failures include:

- `ValidationError` when model values fail model validation;
- `DuplicateKeyError` when a unique or primary-key constraint is violated;
- `IntegrityError` for other integrity violations;
- `DatabaseError` or a backend-specific translated database error for execution failures;
- `ValueError` for incomplete mutation arguments, such as an upsert without required values.

Import database exceptions from `renus.db`:

```python
from renus.db import DuplicateKeyError, ValidationError


try:
    await users.create(User(username="existing", name="Duplicate"))
except DuplicateKeyError:
    print("username already exists")
except ValidationError as exc:
    print(exc.errors)
```

For successful direct mutations, inspect the integer returned by the repository method. Model inserts and saves return model instances instead.

## 13. Atomic groups of mutations

A mutation is not a replacement for an application-level transaction. Wrap related writes in `db.transaction()` or use a unit of work when they must commit or roll back together:

```python
async with db.transaction():
    await users.create(User(username="one", name="One"))
    await users.create(User(username="two", name="Two"))
```

See [`/docs/database/transactions.md`](transactions.md) and [`/docs/database/uow.md`](uow.md) for transaction boundaries and rollback behavior.

## Next steps

- [`/docs/database/repositories.md`](repositories.md) — choose the right repository method.
- [`/docs/database/queries.md`](queries.md) — filter rows and use query-side mutations.
- [`/docs/database/adapters.md`](adapters.md) — understand compilation and backend differences.
