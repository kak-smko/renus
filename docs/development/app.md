# Application

The `App` class is the core of a Renus application. It ties together routing, middlewares, caching, and the ASGI lifespan so a plain Python object can be served by any ASGI server (like uvicorn). You create one `App` instance, register routes on it, and run it.

## Creating an app

Import `App` from `renus.app` and instantiate it:

```python
from renus.app import App

app = App()
```

The `App` constructor accepts a few optional keyword arguments:

| Argument     | Default | Description |
| ------------ | ------- | ----------- |
| `lifespan`   | `None`  | A custom ASGI lifespan context manager to use instead of the default one. |
| `on_startup` | `None`  | A callable (or list of callables) run at server startup. |
| `on_shutdown`| `None`  | A callable (or list of callables) run at server shutdown. |
| `middlewares`| `None`  | A list of ASGI middlewares applied to every request. |

## Reading configuration

`App` reads two settings from the `config.app` configuration module at creation time:

- `debug` — toggles debug behavior. Defaults to `False`.
- `env` — the environment name, such as `"local"` or `"production"`. Defaults to `"local"`.

These are exposed as `app.debug` and `app.env`. When `env` is `"local"`, exceptions are re-raised so you see full tracebacks during development.

## Registering routes

The `App` exposes decorators that register a route when applied to a handler:

- `@app.get(path)` registers a `GET` route.
- `@app.post(path)`, `@app.put(path)`, and `@app.delete(path)` register the matching methods.
- `@app.route(path, method='...')` handles any method, including `WS` for WebSockets, plus `HEAD` and `OPTIONS`.

Each decorator accepts the same optional keyword arguments:

| Argument      | Default | Description |
| ------------- | ------- | ----------- |
| `middlewares` | `None`  | Middlewares applied only to this route. |
| `cache`       | `None`  | Cache TTL in seconds for the route's response. |

For example:

```python
@app.get('/')
def home():
    return TextResponse('Hello, world!')

@app.post('/items')
def create_item():
    return JsonResponse({'created': True})

@app.route('/ws', method='WS')
async def websocket(ws):
    await ws.accept()
    await ws.send_text('connected')
    await ws.close()
```

Dynamic path segments use `{name}` (optionally typed, e.g. `{id:id}`). Under the hood, `App` maps each method to the `Router`'s fluent API, so you can also compose routes directly on `app.router` if you prefer.

## Request injection

A handler that declares a `request` parameter automatically receives the current `Request` object:

```python
@app.get('/whoami')
def whoami(request):
    return JsonResponse({'user-agent': request.headers.get('user-agent')})
```

## Middlewares and caching

Middleware registered on the app apply to every request; middleware passed to an individual route applies only to that route. The two are combined in order (app-level first, then route-level) when a request is dispatched. For details on writing middleware, see [Middlewares](/docs/development/middlewares.md).

The `cache` argument enables response caching for a route for the given TTL in seconds. Cached responses are keyed by the request path and served from the cache on later requests. See [Caching](/docs/development/caching.md) for more.

## Application state

Each `App` carries a `state` dictionary (`app.state`) that you can use to share data across handlers, middlewares, and lifespan handlers.

## The lifespan

By default, `App` builds a lifespan that runs every `on_startup` callable at startup and every `on_shutdown` callable at shutdown. Callables may be sync or `async`, plain functions or async generators. You can provide your own lifespan by passing a context manager to the `lifespan` argument of the `App` constructor.

Startup and shutdown callables may declare `app` and `on_startup` parameters to receive the application instance and a boolean flag:

```python
async def load_db(app, on_startup):
    if on_startup:
        await app.db.connect()

app = App(on_startup=[load_db])
```

See [Lifespan & Background Tasks](/docs/development/lifespan_tasks.md) for details.

## Running the app

Use `app.run()` to start a uvicorn server bound to a host and port:

```python
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, reload=True)
```

`App.run()` forwards these arguments to `uvicorn.run`:

| Argument  | Default        | Description |
| --------- | -------------- | ----------- |
| `app`     | `None`         | Optional ASGI app to serve; defaults to this app. |
| `host`    | `"127.0.0.1"`  | Host address to bind. |
| `port`    | `8000`         | Port to bind. |
| `reload`  | `False`        | Enable auto-reload on code changes. |
| `**options` | —           | Extra options passed through to `uvicorn.run`. |

Because `App` implements the ASGI protocol, you can also run it with a separate ASGI server:

```bash
uvicorn main:app --reload
```

## The ASGI contract

`App.__call__` dispatches over the ASGI `scope["type"]`:

- `http` — builds a `Request` and serves it through the registered routes.
- `websocket` — builds a `WebSocket` and dispatches the matching route.
- `lifespan` — drives the startup/shutdown lifecycle.

It sets `scope["app"]` to the application instance so downstream components can reach it.
