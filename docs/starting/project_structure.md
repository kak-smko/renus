# Project Structure

This page explains how a **Renus** project is organized, so you know where things live
when starting a new application and when exploring the framework itself. It covers two
layouts:

- **A Renus application** — the project you build. The layout mirrors what
  `renus create` scaffolds, so most projects follow a familiar shape.
- **The framework source** — the internals of the `renus` package, for anyone
  reading or contributing to the core.

## A Renus application

The reference layout for a full-stack Renus project is the **Codenus** starter
template, hosted at [github.com/kak-smko/codenus](https://github.com/kak-smko/codenus).
Codenus combines a Renus (Python) backend with Renusify (Vue 3) frontends, and most
serious applications follow this same shape:

```text
codenus/
├── app/                    # Application logic
├── commands/               # CLI commands
├── config/                 # Configuration
│   ├── app.py             # Application settings and environment variables
│   └── database.py        # Database connection and settings
├── extension/             # Extension system
│   └── install.py         # Extension installer
├── frontend/              # Frontend applications (Vue 3 + Vite)
│   ├── admin/             # Admin interface (port 8081)
│   └── index/             # Public interface, PWA-enabled (port 8080)
├── job/                   # Background jobs
├── public/                # Public assets
├── routes/                # API routes
│   ├── index.py           # Route entry point
│   └── web.py             # Web routes
├── storage/               # File storage
├── main.py                # Application entry point
├── requirements.txt       # Python dependencies
└── `.gitignore`
```

### Backend (`app/`, `routes/`, `commands/`, `job/`)

The Python backend is built on Renus and serves the API. Handler code lives under
`app/`, route modules define `Router` instances and are explicitly mounted on the
`App` (often from `routes/index.py`), custom `renus` CLI commands live in
`commands/`, and scheduled or background work goes in `job/`.

### Configuration (`config/`)

Application settings are split by concern:

- `config/app.py` — application settings and environment variables.
- `config/database.py` — the database connection and its configuration.

### Extensions (`extension/`)

Codenus adds optional functionality through a plugin-based extension system. Extensions
install into `extension/` and can add routes, extend models, provide middleware, or
contribute background jobs. For example:

```bash
renus extension codenus/user      # User authentication and management
renus extension codenus/translate # Internationalization support
```

### Frontend (`frontend/`)

Two separate Vue 3 + Vite applications share the backend:

- `frontend/index` — the public, user-facing application (PWA-enabled), served on port
  `8080`.
- `frontend/admin` — the administrative dashboard, served on port `8081`.

### Application entry point (`main.py`)

`main.py` creates the app and runs the ASGI server. In development it launches with hot
reloading and multiple worker processes:

```python
if __name__ == "__main__":
    uvicorn.run("main:app",
                host="0.0.0.0",
                port=4000,
                server_header=False,
                workers=8,
                reload=True,
                log_level="warning")
```

It can also enable end-to-end encryption by assigning a `Crypto` cryptor to
`JsonResponse` and `Request`.

> The full Codenus README describes installation, running, and production deployment in
> detail. For generating a smaller standalone scaffold, see
> [Project Scaffolding](/docs/cli/create.md).

## The framework source

The `renus` package groups functionality into sub-packages by concern:

```text
renus/
├── app/            # The App class, dispatch, handlers, lifespan
├── cache/          # Cache backends (memory, file, redis) and a Cacher facade
├── commands/       # The `renus` CLI (run, create, db, extension, help)
├── config/         # Application configuration handling
├── datastructures/ # Background tasks, multidict, serialization, uploads
├── db/             # ORM: models, query/mutation builders, migrations, adapters
├── log/            # Logging setup, formatters and handlers
├── request/        # Request object, parsers, form decoding, XSS helpers
├── response/       # Response types: text, json, file, streaming, redirects, gzip
├── rich/           # Terminal/CLI helpers (colors, tables, progress, markdown)
├── router/         # Routing engine: registry, path matching, middleware chain
├── schedule/       # Task scheduler and matchers
├── util/           # Shared utilities: codec, concurrency, random, security
├── websockets/     # WebSocket protocol, sessions and messages
├── __init__.py     # Package metadata (__version__)
└── __main__.py     # Enables `python -m renus` to reach the CLI
```

The most important entry points for application writers are `renus.app`
(`App`, `Router`) and the high-level modules covered throughout the Development,
Database, and Security sections of these docs.

## Next steps

Some useful next pages as you explore the framework:

- Build routes and handle requests in [Routing](/docs/development/routing.md) and
  [Request](/docs/development/request.md).
- Define models and query them in [Models & Fields](/docs/database/models.md) and
  [Queries & Mutations](/docs/database/queries.md).
- Generate a project from the CLI in [Project Scaffolding](/docs/cli/create.md).
