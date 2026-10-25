# Renus

[![Latest release](https://img.shields.io/github/v/release/kak-smko/renus)](https://github.com/kak-smko/renus/releases/latest)
[![PyPI version](https://img.shields.io/pypi/v/renus)](https://pypi.org/project/renus/)
[![License](https://img.shields.io/github/license/kak-smko/renus)](https://github.com/kak-smko/renus/blob/master/LICENSE)

**An async-first Python ASGI framework with routing, WebSockets, ORM, caching,
scheduling, and CLI tools in one small core.**

- **Documentation:** [codenus.com/renus](https://codenus.com/renus)
- **Source:** [github.com/kak-smko/renus](https://github.com/kak-smko/renus)

## Features

- ASGI application support for HTTP, WebSockets, and lifespan events
- Decorator-based and fluent routing with typed path parameters
- Text, HTML, JSON, redirect, file, streaming, and private responses
- Application, router, and route-level middleware
- Request parsing for headers, cookies, query parameters, JSON, forms, and uploads
- Built-in XSS protection for form and WebSocket input helpers
- Background tasks and startup/shutdown hooks
- File- and Redis-backed caching, including route and function caching
- Async ORM with models, validation, repositories, queries, mutations, and transactions
- SQLite, MySQL, and MongoDB integrations through optional dependencies
- Database migrations, backup/restore, and plugin hooks
- Fluent task scheduling and a built-in `renus` CLI

## Installation

Renus requires Python 3.11 or newer. Install the core package with pip:

```bash
python -m pip install renus
```

Renus is an ASGI framework. Install the server extra when you want to run an
application with Uvicorn or with `App.run()`:

```bash
python -m pip install "renus[server]"
```

Optional extras are available for additional integrations:

| Extra | Provides |
| --- | --- |
| `server` | Uvicorn |
| `mongo` | MongoDB support via `pymongo` |
| `mysql` | MySQL support via `aiomysql` |
| `redis` | Redis caching support |
| `all` | All runtime integrations |
| `dev` | Development and benchmarking dependencies |

Install from source in editable mode:

```bash
git clone https://github.com/kak-smko/renus.git
cd renus
python -m pip install -e ".[dev]"
```

## Quick start

Install Renus with its Uvicorn server extra:

```bash
python -m pip install "renus[server]"
```

Create `main.py`:

```python
from renus.app import App
from renus.response import JsonResponse, TextResponse

app = App()


@app.get("/")
def home():
    return TextResponse("Hello, world!")


@app.get("/users/{username}")
def user(username):
    return JsonResponse({"name": username})
```

Run the application with Uvicorn:

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Then visit <http://127.0.0.1:8000/> or call the parameterized route:

```bash
curl http://127.0.0.1:8000/users/renus
# {"name":"renus"}
```

You can also use Renus's convenience runner:

```python
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, reload=True)
```

```bash
python main.py
```

## WebSockets

WebSocket routes use `@app.route(..., method="WS")`:

```python
from renus.websockets import WebSocketDisconnect


@app.route("/echo", method="WS")
async def echo(ws):
    await ws.accept()
    try:
        async for message in ws.iter_text():
            await ws.send_text(message)
    except WebSocketDisconnect:
        pass
```

## Database example

Renus includes an async ORM. The following example uses the built-in SQLite
adapter:

```python
from renus.db import Database, DatabaseField, Field, Model, SQLiteAdapter


class User(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(database=DatabaseField(unique=True))
    email: str


async def create_user():
    async with Database(SQLiteAdapter({"database": "storage/app.sqlite"})) as db:
        await db.create_schema([User])
        users = db.repository(User)
        return await users.create(
            User(username="ada", email="ada@example.com")
        )
```

For production applications, initialize shared database resources in an
application lifespan hook and use migrations for schema changes.

## CLI

The package exposes both a `renus` command and a module entry point:

```bash
renus --help
renus --version
python -m renus --help
```

Project commands can be added under a project's `commands/` directory. See the
[CLI documentation](https://codenus.com/renus) for command discovery,
scaffolding, database commands, and extensions.

## Documentation

The full documentation covers:

- [Installation](docs/starting/installation.md)
- [Quick start](docs/starting/quick_start.md)
- [Project structure](docs/starting/project_structure.md)
- [Application and routing](docs/development/app.md)
- [Requests and responses](docs/development/request.md)
- [Middleware](docs/development/middlewares.md)
- [WebSockets](docs/development/websockets.md)
- [Lifespan and background tasks](docs/development/lifespan_tasks.md)
- [Caching and scheduling](docs/development/caching.md)
- [Database, models, queries, and migrations](docs/database/overview.md)
- [Validation and security](docs/security/validation.md)
- [CLI reference](docs/cli/reference.md)

## Benchmarks

The [benchmark guide](benchmarks/README.md) describes the cross-framework HTTP
comparison. GitHub Actions runs it weekly; the latest results are published here.

<!-- benchmark-results:start -->

### Cross-Framework Benchmark Results

Real HTTP/1.1 keep-alive load test of `renus` vs other Python web frameworks. Each framework serves the same routes and is hammered single-process with the bundled stdlib load tester.

- Python: 3.12.15
- Concurrency: 64 keep-alive connections
- Duration: 60.0s per endpoint

> These are **relative** numbers for a single machine/run. Absolute throughput is machine-dependent; rerun and take the median before drawing conclusions.

#### `plain` (`/plain`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| renus | 37,190 | 1.70 | 1.81 | 2.20 | 7.75 |
| pur_uvicorn | 36,616 | 1.72 | 1.85 | 2.32 | 7.83 |
| blacksheep | 36,053 | 1.75 | 1.87 | 2.30 | 8.23 |
| sanic | 36,040 | 1.74 | 2.11 | 2.43 | 10.56 |
| robyn | 35,414 | 1.78 | 1.89 | 2.20 | 9.76 |
| litestar | 29,245 | 2.31 | 2.48 | 3.23 | 11.81 |
| fastapi | 20,374 | 3.32 | 3.47 | 4.73 | 14.68 |

#### `json` (`/json`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| blacksheep | 36,227 | 1.74 | 1.86 | 2.11 | 8.39 |
| sanic | 36,003 | 1.75 | 2.10 | 2.41 | 9.68 |
| pur_uvicorn | 35,999 | 1.75 | 1.88 | 2.37 | 8.98 |
| renus | 35,799 | 1.75 | 1.89 | 2.42 | 8.33 |
| robyn | 35,093 | 1.80 | 1.92 | 2.27 | 10.69 |
| litestar | 28,408 | 2.39 | 2.53 | 3.19 | 15.05 |
| fastapi | 19,433 | 3.51 | 3.66 | 4.06 | 13.70 |

#### `user` (`/user/alice`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| renus | 36,094 | 1.74 | 1.87 | 2.37 | 10.10 |
| sanic | 35,976 | 1.75 | 2.10 | 2.37 | 8.98 |
| pur_uvicorn | 35,885 | 1.75 | 1.87 | 2.40 | 7.60 |
| blacksheep | 35,721 | 1.77 | 1.89 | 2.27 | 7.08 |
| robyn | 32,628 | 1.92 | 2.05 | 2.36 | 10.55 |
| litestar | 24,825 | 2.73 | 2.91 | 3.52 | 12.50 |
| fastapi | 16,220 | 4.10 | 4.75 | 5.26 | 14.15 |

<!-- benchmark-results:end -->

## Development

Install the development dependencies and run the test suite:

```bash
python -m pip install -e ".[dev]"
pytest
```

Run a focused test module while developing:

```bash
pytest tests/test_routing.py
```

## Contributing

Bug reports, documentation improvements, tests, and code contributions are
welcome. Please keep changes focused, add regression tests for behavior changes,
and follow the existing project style.

## Support Renus

If Renus is useful to you, please consider giving the project a star on
[GitHub](https://github.com/kak-smko/renus). It helps others discover the
framework and supports continued development.

A GitHub star is appreciated but voluntary; it is not a condition of using,
copying, modifying, or distributing Renus under the BSD 3-Clause License.

## License

Renus is distributed under the [BSD 3-Clause License](LICENSE).
