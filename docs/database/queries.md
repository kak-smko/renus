# Queries

Renus queries are immutable builders. A repository query describes filters, selected fields, ordering, pagination, relationships, and aggregates; execution happens when you call `all()`, `first()`, `count()`, or `exists()`.

Queries run asynchronously and are bound to the repository that created them. The query builder itself does not execute anything until an execution method is awaited.

## 1. Start a query

Create a query with `repository.query()` or `repository.where()`:

```python
users = db.repository(User)

all_users = await users.query().all()
active_users = await users.where(User.active == True).all()
```

`where()` is an alias for `query()`. Both accept zero or more conditions. A query can also be called directly:

```python
query = users.query()(User.active == True)
```

A query without filters matches every row in the normal scope. Models with soft deletion exclude deleted rows by default.

## 2. Conditions

Model fields expose `Path` objects at the class level. Comparisons create conditions:

```python
users.where(
    User.age >= 18,
    User.active == True,
)
```

Multiple conditions passed to `where()` are combined by the repository as `AND` conditions. The supported field operators are:

| Expression | Meaning |
| --- | --- |
| `User.name == value` | Equal to `value`; `None` becomes `IS NULL` |
| `User.name != value` | Not equal to `value`; `None` becomes `IS NOT NULL` |
| `User.age > value` | Greater than |
| `User.age >= value` | Greater than or equal to |
| `User.age < value` | Less than |
| `User.age <= value` | Less than or equal to |
| `User.role.in_(values)` | In a collection of values |
| `User.role.not_in(values)` | Not in a collection of values |
| `User.name.is_null()` | Is `NULL` |
| `User.name.is_not_null()` | Is not `NULL` |
| `User.name.like("A%")` | Matches a `LIKE` pattern; MongoDB translates `%` and `_` to regex equivalents |
| `User.name.regex(pattern)` | Matches a regular expression |
| `User.age.between(18, 65)` | Inclusive range |

Combine conditions explicitly with `&`, `|`, and `~`:

```python
from renus.db import Q


query = users.where(
    Q(
        (User.active == True) & (User.age >= 18)
        | User.role == "admin"
    )
)
```

`Q(condition1, condition2, ...)` combines its arguments with `AND`. With one argument it returns that condition unchanged. Parenthesize Python expressions when mixing `&` and `|` so the intended grouping is clear.

For a condition on a related collection, use `any()`:

```python
query = users.where(User.posts.any(Post.published == True))
```

Relationship predicates are compiled and evaluated by the selected adapter; 

SQL adapters also support scalar paths through non-embedded relationships:

```python
employees = await employee_repo.where(
    Employee.department.name == "Engineering"
).all()
```

For portable relationship filtering across the built-in adapters, prefer `any()` on the relationship collection or use a condition on the stored foreign-key field. Relationship declarations and relationship-specific behavior are documented in [`/docs/database/models.md`](models.md).

## 3. Execute a query

### `all()`

`all()` returns every matching result:

```python
matching_users = await users.where(User.active == True).all()
```

Without a projection or aggregate, results are hydrated instances of the repository model. Hydrated instances are marked as persisted.

### `first()`

`first()` returns the first matching result or `None`:

```python
user = await users.where(User.username == "ada").first()
if user is not None:
    print(user.name)
```

It applies a limit of one. Add `order_by()` when which row is first matters.

### `count()` and `exists()`

```python
adult_count = await users.where(User.age >= 18).count()
has_admin = await users.where(User.role == "admin").exists()
```

`count()` counts matching rows and ignores query ordering, offset, and limit. `exists()` checks whether at least one row matches and uses a limit of one internally.

## 4. Query immutability

Every builder method returns a new query. The original query remains unchanged and can be reused:

```python
base = users.where(User.active == True)

recent = base.order_by(User.created_at.desc()).limit(10)
admins = base.where(User.role == "admin")

# base still contains only the active condition
```

This makes it safe to keep shared base queries and derive independent variants.

## 5. Select specific fields

Use `select()` for a projection:

```python
rows = await (
    users.where(User.active == True)
    .select(User.id, User.username)
    .all()
)
```

Projection results are dictionaries rather than hydrated `User` instances:

```python
# {"id": ..., "username": ...}
print(rows[0])
```

Nested paths are supported and use the leaf field name as the dictionary key:

```python
rows = await users.query().select(User.profile.city).all()
# {"city": "Paris"}
```

The selected paths are represented by the model fields, so database column names and backend-specific identity mappings remain adapter concerns. MongoDB removes its internal `_id` storage field from results and exposes the model identity as `id` when it is selected or when a model is hydrated.

## 6. Ordering

Use a field path directly for ascending order, or call `asc()` and `desc()` for direction:

```python
rows = await users.query().order_by(
    User.name.asc(),
    User.age.desc(),
).all()
```

`order_by()` accepts multiple paths or ordering objects. Ordering is applied in the order supplied.

## 7. Limit, offset, and pagination

```python
page = await (
    users.query()
    .order_by(User.id.asc())
    .offset(20)
    .limit(20)
    .all()
)

page_three = await (
    users.query()
    .order_by(User.id.asc())
    .paginate(page=3, size=20)
    .all()
)
```

`paginate(page, size)` treats pages as one-based: page 1 starts at offset 0. `cursor(token, field=None)` creates a query that starts strictly after the token (`field > token`). If `field` is omitted, the model primary key is used when available:

```python
next_page = await (
    users.query()
    .order_by(User.id.asc())
    .cursor(last_id, field=User.id)
    .limit(20)
    .all()
)
```

Cursor values are compared by the database and are not opaque encoded tokens. Use a field and ordering with compatible ascending semantics; cursor pagination is not a substitute for a compound cursor when the ordering uses multiple fields. For stable pages, provide an explicit order, especially when using offset pagination.

## 8. Eager-load relationships

Use `include()` to load relationships with the result:

```python
posts = await (
    users.where(User.active == True)
    .include(User.posts)
    .all()
)
```

The included relationship is populated on each returned model according to its relationship configuration. Relationship loading strategies are `lazy` and `joined`; configure them on the relationship declaration. See [`/docs/database/models.md`](models.md) for relationship types and options.

## 9. Soft-delete scopes

Normal queries exclude soft-deleted rows. Use these scopes when the model has soft deletion enabled:

```python
live = await users.query().all()
all_rows = await users.query().with_deleted().all()
deleted = await users.query().only_deleted().all()
```

`with_deleted()` includes both live and deleted rows. `only_deleted()` includes only rows whose deletion timestamp is set. These methods also affect `count()`, `exists()`, projections, and aggregates built from the query.

Restore a deleted row through a repository or query. Restore targets only rows whose deletion timestamp is set:

```python
await users.where(User.username == "ada").restore()
# Equivalent:
await users.restore(User.username == "ada")
```

For a loaded soft-deleted model, pass the instance directly:

```python
deleted = await users.only_deleted().first()
if deleted is not None:
    await users.restore(deleted)
```

## 10. Aggregates and grouping

Import aggregate factories from `renus.db` and add them with `aggregate()`:

```python
from renus.db import Count, Sum


rows = await (
    users.query()
    .group_by(User.role)
    .aggregate(
        Count().as_("user_count"),
        total_age=Sum(User.age),
    )
    .having(Count() > 1)
    .all()
)
```

Aggregate results are dictionaries. The aggregate factories are:

- `Count(path=None, distinct=False)`
- `Sum(path, distinct=False)`
- `Avg(path, distinct=False)`
- `Min(path)`
- `Max(path)`

An aggregate can receive an alias with `.as_(name)`. Keyword arguments to `aggregate()` use the keyword as the alias:

```python
summary = await users.query().aggregate(
    active_count=Count(User.id, distinct=True),
).all()
```

`distinct=True` is supported by `Count`, `Sum`, and `Avg`; it applies to the aggregate path before the function is calculated. For example:

```python
summary = await users.query().aggregate(
    unique_roles=Count(User.role, distinct=True),
    unique_age_total=Sum(User.age, distinct=True),
    unique_age_average=Avg(User.age, distinct=True),
).all()
```

`having()` filters grouped or aggregate results after grouping. Pass multiple conditions to combine them with `AND`, or compose aggregate conditions with `&` and `|`:

```python
rows = await (
    users.query()
    .group_by(User.role)
    .aggregate(rows=Count(User.id), total_age=Sum(User.age))
    .having((Count(User.id) >= 2) & (Sum(User.age) > 100))
    .all()
)
```

Group fields are included in the returned dictionaries, including all fields passed to `group_by()`.

## 11. Distinct results

Use `distinct()` to request distinct rows:

```python
rows = await users.query().select(User.role).distinct().all()
```

Distinct projections return dictionaries, as all projected queries do.

## 13. Query-side mutations

A query can update or delete the rows selected by its filters:

```python
updated = await users.where(User.active == False).update({"role": "inactive"})
deleted = await users.where(User.active == False).delete()
hard_deleted = await users.where(User.role == "expired").hard_delete()
```

`update()` and `delete()` use the query filters. Query `limit()`, `offset()`, and ordering are not used to restrict these mutation operations; use precise filter conditions or the repository mutation methods described in [`/docs/database/mutations.md`](mutations.md).


## 14. Backend behavior

The query builder produces a backend-neutral query structure. SQL adapters compile it to parameterized SQL; MongoDB compiles it to filters, projections, sort specifications, and aggregation pipelines. Relationship predicates are part of this compilation: SQL uses `EXISTS` joins, including many-to-many through tables, while MongoDB uses `$lookup` stages for non-embedded relationships.

Embedded data is also backend-specific. SQL adapters query normalized auxiliary tables, including nested embedded paths; MongoDB queries nested documents and arrays with `$elemMatch` where needed. Nested projections return the selected leaf field under its field name on both backends.

The same public query API is intended to work across the built-in adapters, but backend support can vary for advanced operations. In particular, cursor comparisons use `>` against the selected field. See [`/docs/database/adapters.md`](adapters.md) when choosing a backend.

## Next steps

- [`/docs/database/repositories.md`](repositories.md) — create repositories and persist models.
- [`/docs/database/mutations.md`](mutations.md) — use write operations directly.
- [`/docs/database/models.md`](models.md) — define fields and relationships used in conditions.
