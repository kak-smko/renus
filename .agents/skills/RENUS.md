---
name: renus-framework
description: Build, explain, debug, test, and extend applications with the Renus v3 Python ASGI framework in this repository, from installation and first routes through routing, middleware, requests/responses, WebSockets, lifespan, caching, scheduling, validation, the async ORM, migrations, CLI commands, security, and production readiness.
---

# Renus Framework: 0–100% Engineering Guide

Use this skill whenever the task involves the Renus framework, a Renus application, or this repository's `renus` package. Treat the repository implementation and tests as the final authority. The checked-in documentation is useful but incomplete in places: `renus/docs/menu.json`.

## Operating principles

1. **Inspect before coding.** Start with the relevant package and tests. The main framework areas are:
   - `renus/app`: `App`, ASGI dispatch, handlers, lifespan.
   - `renus/router`: `Router`, path convertors, middleware chain.
   - `renus/request`: `Request`, body/form parsers, cookies, headers, query parsing, XSS helpers.
   - `renus/response`: response classes, status codes, streaming, files, redirects, gzip, errors.
   - `renus/websockets`: WebSocket session/protocol/messages/state.
   - `renus/db`: models, fields, repositories, immutable queries, mutations, adapters, transactions, migrations.
   - `renus/cache`: file/Redis backends, `Cache`, route caching, function cache decorator.
   - `renus/schedule`: fluent scheduler, matcher, runner, persistent last-run cache.
   - `renus/config`, `renus/commands`, `renus/rich`, and `renus/util`: configuration, CLI, terminal helpers, and shared utilities.
2. **Prefer public exports.** Import application-facing objects from `renus.app`, `renus.router`, `renus.request`, `renus.response`, `renus.websockets`, `renus.db`, and `renus.cache` where available. Use internal modules only when implementing or debugging framework internals.
3. **Preserve async boundaries.** Request handlers, database operations, WebSocket operations, and background tasks may be asynchronous. Do not block the event loop with synchronous I/O in an async handler; use an existing async API or explicitly move blocking work off-loop.
4. **Keep the patch surgical.** Follow existing naming and patterns. Do not alter unrelated framework behavior. If a behavior is unclear, reproduce it with a focused test before changing it.

## The 0–100% learning and implementation path

Use the stage that matches the user's request. Do not force advanced database or deployment concerns into a simple route task.

### 0–10%: install and orient

- Requirements from `pyproject.toml`: Python `>=3.11` for this checkout; runtime dependencies are `anyio>=3.7` and `orjson>=3.10`.
- Optional extras:
  - `renus[server]` for `uvicorn`.
  - `renus[mongo]` for `pymongo`.
  - `renus[mysql]` for `aiomysql`.
  - `renus[redis]` for Redis caching.
  - `renus[all]` for all backend/server extras.
  - `renus[dev]` for development/benchmark dependencies.

- Verify the installed package with:
  ```bash
  python -c "import renus; print(renus.__version__)"
  ```
- The package exposes a `renus` console script and `python -m renus` entry point. The CLI discovers framework commands from `renus.commands` and project commands from a project's `commands/` directory.

### 10–20%: first HTTP application

Canonical minimal application:

```python
from renus.app import App
from renus.response import JsonResponse, TextResponse

app = App()

@app.get("/")
async def home():
    return TextResponse("Hello, world!")

@app.get("/users/{username}")
async def user(username):
    return JsonResponse({"name": username})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, reload=True)
```

- Handlers can be async.
- A handler may return a `Response`; non-`Response` results are converted by dispatch, but explicit response classes are clearer and safer for status/headers/media type.
- Run with `python main.py`, or install the server extra and run `uvicorn main:app --host 127.0.0.1 --port 8000 --reload`.
- `App` is an ASGI callable and dispatches `http`, `websocket`, and `lifespan` scopes. It sets `scope["app"]` to the app instance.

### 20–30%: routing and controllers

App decorators:

```python
@app.get("/items")
async def index(): ...

@app.post("/items")
async def store(): ...

@app.put("/items/{id:int}")
async def update(id): ...

@app.delete("/items/{id:id}")
async def delete(id): ...

@app.route("/socket", method="WS")
async def socket(ws): ...
```

Supported path convertors in the current router include:

- `{name}` or `{name:str}`: non-slash string.
- `{id:int}`: integer.
- `{value:float}`: float.
- `{path:path}`: multi-segment path.
- `{id:id}`: configured Renus `ID` representation; verify database ID configuration before relying on URL syntax.
- `{flag:bool}`: literal `true`/`false` converted to `bool`.
- `{id:uuid}`: canonical UUID converted to `uuid.UUID`.

`Router` fluent API and controllers:

```python
from renus.router import Router

class ItemController:
    def __init__(self, request):
        self.request = request

    async def index(self):
        return JsonResponse([])

    async def show(self, id):
        return JsonResponse({"id": id})

router = Router(prefix="/api/v1")
router.get("/items", ItemController, "index")
router.get("/items/{id:int}", ItemController, "show")
```

Important routing behavior:

- `Router` registrations enter the shared `RouteRegistry`; an `App()` resolves them without a separate mount operation.
- `Router(prefix=..., middlewares=..., subdomain=...)` supports scoped groups with `with router.group(...) as group:`.
- `crud(path, Controller)` registers conventional `index`, `store`, `update`, and `delete` routes; use only when the controller follows that contract.
- Static paths are resolved before parameterized paths. Registration order matters for parameterized matches.
- The registry normalizes trailing slashes, checks subdomains, and rejects null bytes/path traversal (`..`). Use `RouteRegistry().summary()` while debugging route registration.
- Use `RouteRegistry.reset()`/`clear()` only in tests or controlled reconfiguration; it is a shared singleton.

### 30–40%: request input and responses

Inject the request by declaring a `request` parameter:

```python
@app.get("/whoami")
def whoami(request):
    return JsonResponse({
        "agent": request.user_agent,
        "path": request.full_path,
        "query": request.query_params,
    })
```

Useful request attributes include `method`, `url`/`full_path`, `base_path`, lowercase `headers`, parsed `cookies`, `query_params`, `client`, `ip`, `subdomain`, `user_agent`, and mutable `request.state`.

Read bodies deliberately:

```python
@app.post("/payload")
async def payload(request):
    form = await request.form()          # JSON, urlencoded, or multipart
    raw = await request.body()           # cached bytes
    return JsonResponse({"received": form})
```

- `request.body()` caches the complete body and enforces configured size limits.
- `request.stream()` is one-shot and raises on a second consumption.
- `request.form()` sanitizes string input for XSS; `request.form_unsafe()` skips sanitization and is only appropriate when the application sanitizes explicitly.
- Multipart uploads produce `UploadFile` values; inspect `renus/datastructures/uploads.py` before relying on upload details.
- Request limits include body, header count/size, cookie count/size, and query-string size. Configure and test them at untrusted boundaries.
- `request.state` is the per-request coordination dictionary. Missing attributes may resolve from `app.state` and then request state.

Response selection:

```python
from renus.response import (
    FileResponse, HtmlResponse, JsonResponse, RedirectResponse,
    Status, StreamingResponse, TextResponse, abort,
)

return TextResponse("ok")
return HtmlResponse("<h1>ok</h1>")
return JsonResponse({"ok": True})
return RedirectResponse("/login", status_code=Status.HTTP_302_FOUND)
return FileResponse("static/report.pdf", filename="report.pdf")
return StreamingResponse(stream(), media_type="text/plain")
abort("not found", Status.HTTP_404_NOT_FOUND)
```

Use response objects for headers, cookies, status, media type, background tasks, and optional cryptors. Available exports include `Response`, `TextResponse`, `HtmlResponse`, `JsonResponse`, `JsonResponseRedirect`, `RedirectResponse`, `StreamingResponse`, `FileResponse`, `PrivateResponse`, `Status`, `HTTPException`, `abort`, `abort_if`, and `abort_unless`.

### 40–50%: middleware, lifecycle, and application state

Recommended onion middleware signature:

```python
async def auth(request, method, res):
    if not request.headers.get("authorization"):
        return JsonResponse({"msg": "Unauthorized"}, Status.HTTP_401_UNAUTHORIZED)
    return await method(**res["args"])
```

Register at app, router, or route level:

```python
app = App(middlewares=[global_middleware])

@app.get("/private", middlewares=[auth])
async def private(): ...
```

- Onion middleware receives `(request, method, res)`, can run before and after the next handler, rewrite `res["args"]`, and short-circuit by not calling `method`.
- Legacy middleware takes only `request`; it must be async and return exactly `True` to continue. Any other result becomes the short-circuit result.
- Middleware order is app-level first, then router/route-level. The chain wraps in reverse so the first listed middleware is outermost.
- The same chain applies to WebSockets, where a short-circuit closes the connection instead of returning an HTTP response.
- Route-level response cache lookup occurs inside endpoint dispatch, so middleware wraps cached dispatch too.

Lifespan and state:

```python
async def startup(app, on_startup):
    if on_startup:
        app.state["db"] = await open_pool()

async def shutdown(app, on_startup):
    if not on_startup:
        await app.state["db"].close()

app = App(on_startup=[startup], on_shutdown=[shutdown])
```

Startup/shutdown callbacks may be sync or async and may declare `app` and `on_startup`. A custom `@asynccontextmanager` can be passed as `App(lifespan=...)`. Use `app.state` for resources shared across handlers and middleware.

Background tasks run after the response is sent:

```python
from renus.datastructures import Background

async def record_audit(user_id):
    ...

return JsonResponse(
    {"ok": True},
    background=Background(record_audit, user_id),
)
```

`Background` is async-only in the current implementation. Do not use it as a durable job queue; use an external queue for work that must survive process failure.

### 50–60%: WebSockets and caching

WebSocket route:

```python
from renus.websockets import WebSocketDisconnect

@app.route("/echo", method="WS")
async def echo(ws):
    await ws.accept()
    try:
        async for text in ws.iter_text():
            await ws.send_text(text)
    except WebSocketDisconnect:
        pass
```

WebSocket essentials:

- Call `await ws.accept()` before sending.
- Use `receive_text`, `receive_bytes`, `receive_json`, or async iterators.
- Use `send_text`, `send_bytes`, and `send_json`; JSON supports text or binary mode.
- Close with `await ws.close(code=...)`; invalid state transitions raise `WebSocketProtocolError`.
- Handle `WebSocketDisconnect`, and validate/sanitize client messages. Default text/JSON receive helpers protect against XSS unless `protect=False` is explicitly chosen.

Route response caching:

```python
@app.get("/slow-report", cache=60)
async def report():
    return JsonResponse(await build_report())
```

General cache API:

```python
from renus.cache import Cache

cache = Cache(prefix="app:")
await cache.aput("key", {"value": 1}, expire=60)
value = await cache.aget("key")
count = await cache.aincrement("hits", 1)
```

- Drivers are `file` (embedded SQLite, default) and `redis` (optional dependency).
- Use `Cache(driver="redis")` only when Redis is configured and installed.
- TTL `< 0` or `None` means no expiry; `get` returns the default for missing/expired keys.
- Async variants include `aput`, `aget`, `aincrement`, `aexpire`, `adelete`, and `adelete_expired`.
- The `@cache(seconds)` decorator caches function results using a derived key; inspect key behavior before using it for security-sensitive or user-specific results.
- Never route-cache personalized or authorization-dependent responses without ensuring the cache key includes the relevant identity and variation dimensions. The built-in route cache key is based on `request.full_path`.

### 60–75%: data modeling and the async ORM

Basic model:

```python
from renus.db import DatabaseField, Field, Model

class User(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(database=DatabaseField(unique=True))
    email: str
    active: bool = True

    class Meta:
        timestamps = True
        soft_delete = True
```

Model rules:

- Type annotations define expected values, nullability, and inferred storage types.
- Fields without defaults are required unless nullable; use `str | None` for nullable values.
- `Field` owns defaults, default factories, validation, descriptions, conversion, and sensitive masking.
- `DatabaseField` owns column name, primary key/generation, indexes/uniqueness, nullability, foreign keys, immutability, and comments.
- Use `Field(default_factory=list)`/similar for per-instance mutable defaults.
- `Model.validate(payload)` accepts a dictionary or JSON string/bytes and raises `ValidationError` with structured `.errors`.
- Built-in rules live in `renus.db.validation.rules`: `Required`, `MinLen`, `MaxLen`, `Email`, `In`, `Regex`, `Min`, `Max`, `Schema`, `Each`, `Convert`, and others. Validation is not authorization.
- Relationships include `Embedded`, `EmbeddedMany`, `OneToOne`, `OneToMany`, `ManyToOne`, `ManyToMany`, and `Reference`; inspect relationship metadata and tests before designing complex joins.

Database setup with SQLite:

```python
from renus.db import Database, SQLiteAdapter

db = Database(SQLiteAdapter({"database": "storage/app.sqlite"}))
await db.connect()
await db.create_schema([User])
users = db.repository(User)
```

Prefer a context manager for short-lived operations:

```python
async with Database(SQLiteAdapter({"database": ":memory:"})) as db:
    await db.create_schema([User])
    users = db.repository(User)
```

MySQL and MongoDB are optional backend integrations. Use named adapters for multiple connections:

```python
db = Database(adapters={"primary": primary, "analytics": analytics})
repo = db.repository(User, connection="analytics")
```

Persistence:

```python
user = await users.create(User(username="ada", email="ada@example.com"))
user.email = "ada@example.com"
await users.save(user)
created = await users.create_many([...])
rows = await users.update(User.username == "ada", {"active": False})
await users.delete(User.username == "ada")
await users.hard_delete(User.username == "temporary")
await users.create(
    User(username="ada", email="ada@example.com")
)
await users.update(User.username == "ada", {"email": "ada@new.example.com"})
```

Query builders are immutable and asynchronous:

```python
base = users.where(User.active == True)
recent = await base.order_by(User.id.desc()).limit(20).all()
first = await base.first()
count = await base.count()
exists = await base.exists()
projection = await base.select(User.id, User.username).all()
```

Supported query capabilities include comparisons, `in_`, `not_in`, null checks, `like`, `regex`, `between`, logical `&`/`|`/`~`, `Q(...)`, ordering, offset/limit/pagination/cursor, `include`, `group_by`, `aggregate`, `having`, `distinct`, and soft-delete scopes `with_deleted`/`only_deleted`. Aggregates include `Count`, `Sum`, `Avg`, `Min`, and `Max`.

Use transactions for atomic writes:

```python
async with db.transaction():
    await users.create(first_user)
    await users.create(second_user)
```

Use `db.unit_of_work()` when several repositories share a transaction. Do not assume nested transactions are supported; verify the adapter implementation.

### 75–85%: migrations, backup, plugins, and scheduling

Migrations:

```python
migrations = db.migration_manager(path="migrations")
path = migrations.create("add status to users")
await migrations.upgrade()
statuses = await migrations.status()
assert await migrations.check()
await migrations.downgrade()
```

Migration file shape:

```python
from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.add_column("users", Column("status", "str", default="active"))

async def downgrade(adapter):
    await adapter.drop_column("users", "status")
```

- Names are sortable versioned stems such as `0001_create_users.py`.
- Applied migrations are checksum-tracked in `_db_migrations`; do not edit an applied migration as a normal workflow.
- `upgrade(target=..., fake=True)` and `downgrade(..., fake=True)` change tracking without executing schema operations.
- Use adapter DDL methods and check backend support.
- `db.backup(...)` and `db.restore(...)` are async adapter operations; test restore behavior before using it as a disaster-recovery guarantee.

Database plugins:

- `Database.use(plugin)` registers a plugin with lifecycle hooks.
- Adapter registration helpers are exported from `renus.db`: `register_adapter`, `get_adapter`, `has_adapter`, `unregister_adapter`, and reset/clear helpers.
- Keep plugin side effects explicit and cover connect/query/mutation/error hooks with tests.

Scheduler:

```python
from renus.schedule import Schedule

Schedule().every(5).minutes().do("flush", flush_metrics)
Schedule().every().days().at(hour=9, minute=30).do("report", send_report)
```

- Units: `weeks`, `days`, `hours`, `minutes`, `seconds`.
- `at(...)` narrows matching time; `forget(...)` excludes values; `max_try(n)` controls retries; `timedelta(minutes)` offsets evaluation.
- `do` registers only when due and matching. `run(parallel=False)` runs inline; default parallel execution uses worker threads.
- Job keys deduplicate through the cache and a per-key lock; same-key jobs do not overlap.
- Renus does not provide an automatic scheduler loop. Drive it from a controlled lifespan task, and plan cancellation/shutdown explicitly.

### 85–95%: CLI, configuration, security, and operational behavior

CLI behavior from `renus.commands.cli`:

```bash
renus
renus --help
renus --version
python -m renus --help
```

The CLI looks for commands in `commands.<name>`/`commands.<name>.run` in the project first, then in `renus.commands`. A project command can expose a `run` callable or a `BaseCommand` subclass:

```python
from renus.commands.base import BaseCommand

class Command(BaseCommand):
    name = "greet"
    description = "Greet the operator"

    def run(self, args=None):
        print("hello")
        return 0
```

Keep CLI commands deterministic, return nonzero codes on failures, and test command discovery/argument handling. Do not assume a command documented in a missing page exists; inspect `renus/commands`.

Configuration:

- `Config("app")` and `Config("database")` load project modules when present and cache their values.
- Use `Config("app").get("key", default)` or attribute access for settings.
- `App` reads `debug` and `env`; request/cache/database components read additional keys. Search the source for the exact key before documenting or changing configuration.
- Avoid putting secrets in source-controlled config. Load them from protected environment/deployment configuration.

Security baseline:

- Validate every client-controlled boundary. Use models or `Validate(data).rules(...)` and strict allowlists/schemas where practical.
- Keep validation separate from authorization and authentication.
- Use body/header/cookie/query size limits; constrain string lengths, file extensions/sizes, collection depth, and nested schemas.
- `request.form()` and WebSocket text/JSON receiving protect against XSS by default; do not blindly use unsafe variants.
- Reject path traversal and null bytes; do not concatenate untrusted paths without validation.
- Use HTTPS. Optional body encryption is not a replacement for TLS, authentication, authorization, key rotation, replay protection, or password hashing.
- If configuring a cryptor, assign the class/callable expected by Renus (`Request.cryptor = Crypto`, `JsonResponse.cryptor = Crypto`), not an incorrectly pre-created instance. Verify the request/response wire format end-to-end; the repository docs call out a raw-bytes versus base64 caveat.
- Never log credentials, bearer tokens, encryption keys, or raw sensitive payloads. Use `Field(..., sensitive=True)`/existing masking behavior where appropriate.

### 95–100%: tests, performance, and production readiness

Testing patterns:

- Run the smallest relevant test file first, e.g. `pytest tests/test_routing.py`.
- Run the full suite with `pytest`.
- Async tests use the repository's existing pytest setup and `pytest.mark.asyncio`; follow nearby tests rather than adding a new test framework.
- Build focused ASGI test doubles for `scope`, `receive`, and `send` when testing app dispatch. See `tests/test_app.py` for message accumulator patterns.
- Reset shared global state in fixtures: `RouteRegistry.reset()`, `Cache.clear_instances()`, and any relevant `Config` cache state.
- For database tests, use SQLite `:memory:` or a temporary file, connect/create schema, exercise repository behavior, and disconnect. Test transaction rollback and adapter-specific differences.
- Assert response status, headers, body, middleware ordering/short-circuit behavior, route parameter conversion, WebSocket state transitions, and cache expiry—not just that a handler returns.

Production checklist:

- Use an external ASGI server (`uvicorn`) and configure host, port, workers, reload, and logging intentionally. Do not combine reload and production worker assumptions without verifying uvicorn behavior.
- Set `env`/debug configuration deliberately; local mode may re-raise exceptions for tracebacks.
- Open/close database resources in lifespan hooks and keep them in `app.state`.
- Use migrations for existing schemas; do not rely on `create_schema` alone for deployed changes.
- Choose file cache versus Redis based on process topology and durability requirements. Namespace keys and define TTLs.
- Bound request sizes and upload handling; protect files and storage paths.
- Add health checks, structured logs, error handling, metrics, and graceful shutdown as the deployment requires.
- Benchmark only after correctness. The project has `benchmarks/`; compare against the current implementation and avoid optimizing unmeasured paths.


## Repository reference map

Use these as starting points, not as substitutes for source inspection:

- Getting started: `docs/starting/installation.md`, `docs/starting/quick_start.md`, `docs/starting/project_structure.md`.
- Web development: `docs/development/app.md`, `routing.md`, `request.md`, `response.md`, `middlewares.md`, `websockets.md`, `lifespan_tasks.md`, `caching.md`, `scheduling.md`, `logging.md`, `rich.md`.
- Database: `docs/database/overview.md`, `models.md`, `fields.md`, `queries.md`, `mutations.md`, `repositories.md`, `adapters.md`, `transactions.md`, `migrations.md`, `backup.md`, `id.md`.
- Security: `docs/security/validation.md`, `xss.md`, `encryption.md`, `random_secrets.md`.
- Tests: `tests/test_app.py`, `test_routing.py`, `test_request.py`, `test_response.py`, `test_websockets.py`, `test_cache.py`, `test_schedule.py`, `test_validation.py`, and `tests/db/`.

When docs and implementation conflict, state the conflict, cite the relevant source/test, and implement the behavior that is actually supported by the current checkout unless the user explicitly requests a compatibility change.
