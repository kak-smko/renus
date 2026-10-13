# Lifespan & Background Tasks

Open shared resources in startup hooks and close them in shutdown hooks. This app keeps a SQLite database connection open for its lifetime and records a visit after sending the response:

```python
from renus.app import App
from renus.datastructures import Background
from renus.db import Database, Model, SQLiteAdapter
from renus.response import JsonResponse


class Visit(Model):
    message: str


async def open_database(app, on_startup):
    if on_startup:
        db = Database(SQLiteAdapter({"database": "app.sqlite"}))
        await db.connect()
        await db.create_schema([Visit])
        app.state["db"] = db


async def close_database(app, on_startup):
    if not on_startup:
        db = app.state.pop("db", None)
        if db is not None:
            await db.disconnect()


app = App(
    on_startup=[open_database],
    on_shutdown=[close_database],
)


async def record_visit(db):
    visits = db.repository(Visit)
    await visits.create(Visit(message="visit recorded"))


@app.get("/visit")
async def visit():
    return JsonResponse(
        {"ok": True},
        background=Background(record_visit, app.state["db"]),
    )
```

The startup callback connects before requests are served; the shutdown callback closes the connection. `Background` awaits an async callable after the response body has been sent, so the client does not wait for this insert. It is not a durable queue: work can be lost if the process stops before it finishes. For durable jobs, use a queue designed for that purpose.

See [Lifespan & Background Tasks](../development/lifespan_tasks.md) for callback arguments, custom lifespan contexts, and response timing.
