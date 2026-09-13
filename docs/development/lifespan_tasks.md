# Lifespan & Background Tasks

Renus separates work that happens *around* a request from work that happens *while* handling it:

- **Lifespan** handlers run when the server starts up and shuts down. They are the right place to open database pools, load caches, or start resources that outlive individual requests.
- **Background tasks** run *after* a response has been sent to the client. They are the right place for work you do not want the caller to wait on, like sending an email or writing an audit log.

Both are driven by the ASGI `lifespan` protocol, which ASGI servers such as uvicorn invoke automatically.

## The lifespan

When you create an `App`, Renus builds a default lifespan that runs every `on_startup` callable at startup and every `on_shutdown` callable at shutdown, in registration order:

```python
from renus.app import App

async def connect_db(app, on_startup):
    if on_startup:
        app.db = await create_pool()

async def close_db(app, on_startup):
    if not on_startup:
        await app.db.close()

app = App(
    on_startup=[connect_db],
    on_shutdown=[close_db],
)
```

Startup and shutdown callables may be **sync or async**, and plain functions or async generators. They can be passed as a single callable or an iterable of callables.

### Handler arguments

A handler that declares any parameters is called with two keyword arguments:

| Argument     | Description |
| ------------ | ----------- |
| `app`        | The application instance. |
| `on_startup` | `True` during startup, `False` during shutdown. |

A handler with no parameters is called with no arguments.

```python
async def open_db(app, on_startup):
    if on_startup:
        app.state["db"] = await create_pool()
```

This is why the example above uses `on_startup` to decide which branch to run: the same callable can serve as both a startup and a shutdown handler.

### Sharing application state

Because handlers receive the `app` instance, they can stash resources in `app.state` for handlers and middlewares to use later. See [Application](/docs/development/app.md) for more on `app.state`.

## Custom lifespan

You can replace the default lifespan entirely by passing a context manager (or generator) to the `lifespan` argument of the `App` constructor:

```python
from renus.app import App
from contextlib import asynccontextmanager

@asynccontextmanager
async def my_lifespan(app):
    await startup_work()
    yield
    await shutdown_work()

app = App(lifespan=my_lifespan)
```

The lifespan is an async generator or async context manager that yields exactly once. When it yields, the server signals `lifespan.startup.complete`; when the generator finishes, it signals `lifespan.shutdown.complete`. If startup raises before the first yield, Renus sends a `lifespan.startup.failed` message containing the traceback. In the `local` environment the exception is re-raised so you see the full traceback during development.

## Background tasks

A **background task** is a callable that runs after the response body has been sent. Use the `Background` class from `renus.datastructures` to wrap a callable and its arguments, then pass it to any response via the `background` argument:

```python
from renus.response import TextResponse
from renus.datastructures import Background

async def send_receipt(order_id):
    email_service.send(order_id)

@app.get('/checkout')
async def checkout(order_id):
    # Return immediately; the email is sent after the response is delivered.
    return TextResponse('Order received', background=Background(send_receipt, order_id))
```

`Background` stores the callable and its arguments and executes them once the response has been sent. `Background` is **async-only**: pass an `async` callable and it is awaited directly on the event loop.

```python
from renus.response import JsonResponse
from renus.datastructures import Background

async def slow_export(user_id):
    await generate_report(user_id)

@app.get('/export')
async def export(user_id):
    return JsonResponse({"started": True}, background=Background(slow_export, user_id))
```

All response types honor the `background` argument. It runs after the body is sent for regular responses, after the stream finishes for streaming responses, and after the file (and any `on_end` callback) for file responses. See [Response](/docs/development/response.md) for details.

## Example: startup, shutdown, and a background task together

```python
from renus.app import App
from renus.response import JsonResponse
from renus.datastructures import Background
from renus.db import create_pool

async def open_pool(app, on_startup):
    if on_startup:
        app.state["pool"] = await create_pool()

async def record(pool):
    await pool.execute("INSERT INTO visits DEFAULT VALUES")

app = App(on_startup=open_pool)

@app.get('/visit')
async def visit():
    pool = app.state["pool"]
    return JsonResponse({"ok": True}, background=Background(record, pool))
```

The database pool is created once at startup, stored on `app.state`, and reused across requests. Each visit records the row in the background after the caller receives their response.

