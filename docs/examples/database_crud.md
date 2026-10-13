# Database CRUD

This runnable script defines a model, creates its SQLite schema, inserts a user, updates it, and reads it back. Save it as `crud.py`:

```python
import asyncio

from renus.db import Database, DatabaseField, Field, Model, SQLiteAdapter


class User(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(database=DatabaseField(unique=True))
    email: str


async def main() -> None:
    async with Database(SQLiteAdapter({"database": "app.sqlite"})) as db:
        await db.create_schema([User])
        users = db.repository(User)

        user = await users.create(
            User(username="ada", email="ada@example.com")
        )
        user.email = "ada.lovelace@example.com"
        await users.save(user)

        saved = await users.where(User.id == user.id).first()
        print(saved.username, saved.email)


if __name__ == "__main__":
    asyncio.run(main())
```

Run it with `python crud.py`. The async database context connects on entry and disconnects on exit. `create_schema()` is useful for a new or local database; use migrations to evolve a schema that already contains application data. The `unique=True` constraint also means running this exact insert repeatedly will fail on the duplicate username—use a fresh database or choose a new username.

See [Database Overview](../database/overview.md) for lifecycle, repositories, and persistence operations.
