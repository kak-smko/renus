# Database Queries

Repository queries are asynchronous and immutable: each filter or ordering call returns a query builder, and execution happens when you await a terminal method.

```python
import asyncio

from renus.db import Database, Model, SQLiteAdapter


class User(Model):
    username: str
    active: bool = True


async def main() -> None:
    async with Database(SQLiteAdapter({"database": ":memory:"})) as db:
        await db.create_schema([User])
        users = db.repository(User)
        await users.create(User(username="ada", active=True))
        await users.create(User(username="grace", active=False))
        await users.create(User(username="katherine", active=True))

        active_users = users.where(User.active == True)
        names = await active_users.order_by(User.username.asc()).all()
        first_active = await active_users.first()
        active_count = await active_users.count()

        print([user.username for user in names])
        print(first_active.username, active_count)


if __name__ == "__main__":
    asyncio.run(main())
```

The base `active_users` query can be reused because builder operations do not mutate it. With no projection, `all()` and `first()` return model instances. See [Queries](../database/queries.md) for operators, pagination, projections, and aggregates.
