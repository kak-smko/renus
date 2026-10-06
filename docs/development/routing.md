# Routing

Routing maps an incoming request — its method and path — to a handler. In Renus you describe routes on the `App` or on a standalone `Router`, and a registry compiles them into a matcher used to resolve every request.

Routes may target plain functions (`func`) or methods on a *controller* class.

## Registering routes

### With `App` decorators

The quickest way to register a route is with a decorator on the `App`:

```python
from renus.app import App
from renus.response import TextResponse

app = App()

@app.get('/')
async def home():
    return TextResponse('Hello, world!')
```

The `App` exposes `@app.get`, `@app.post`, `@app.put`, `@app.delete`, and `@app.route(path, method='...')` for any method, including `WS`, `HEAD`, and `OPTIONS`. Decorators also accept `middlewares` and (for `GET`/`HEAD`) a `cache` TTL.

### With the `Router` fluent API

Create a `Router` and register routes with its fluent methods. Routers collect definitions without registering them globally; mount a router explicitly on an `App` or include it in another router:

```python
from renus.app import App
from renus.router import Router

r = Router()
r.get('/items', ItemController, 'index')
r.post('/items', ItemController, 'store')
r.put('/items/{id:id}', ItemController, 'update')
r.delete('/items/{id:id}', ItemController, 'delete')

app = App()
app.include(r)
```

Each method takes the path, an optional controller, a handler name or callable, and optional `middlewares` and `cache`:

| Method     | HTTP / WS method |
| ---------- | ---------------- |
| `.get(path, ...)`    | `GET` |
| `.head(path, ...)`   | `HEAD` |
| `.post(path, ...)`   | `POST` |
| `.put(path, ...)`    | `PUT` |
| `.delete(path, ...)` | `DELETE` |
| `.option(path, ...)` | `OPTIONS` |
| `.ws(path, ...)`     | `WS` (WebSocket) |

Each `App` owns its route registry. Router definitions are isolated until mounted with `app.include(router)`, so the same router can be mounted on multiple apps with different prefixes or middleware.

## Path parameters

Use `{name}` in a path to capture a segment, optionally typed with a colon:

```python
@app.get('/user/{id:id}')
async def show_user(id):
    return JsonResponse({'id': str(id)})
```

The available types and their regex are:

| Type     | Matches                                                      | Converts to    |
| -------- | ------------------------------------------------------------ | -------------- |
| `str`    | any non-slash segment                                        | `str`          |
| `int`    | `[0-9]+`                                                     | `int`          |
| `float`  | digits with optional decimal fraction                        | `float`        |
| `path`   | one or more `segment/…` segments (a full sub-path)           | `str`          |
| `id`    | a Renus Id                              | `ID`     |
| `bool`   | `true` or `false`                                            | `bool`         |
| `uuid`   | a canonical UUID string                                      | `uuid.UUID`    |

The type is the default when omitted, so `{name}` is equivalent to `{name:str}`. Matched values are converted before being passed to the handler, so `{id:int}` arrives as an `int`.

## Controllers

A route can target a method on a controller class. The handler position accepts the *method name* as a string and the registry calls it on an instance:

```python
class ItemController:
    def __init__(self, request):
        self.request = request

    async def index(self):
        return JsonResponse([...])

    async def show(self, id):
        return JsonResponse({...})
```

Wire it up with the fluent API:

```python
r = Router()
r.get('/items', ItemController, 'index')
r.get('/items/{id:id}', ItemController, 'show')
```

When a controller's `__init__` declares a `request` parameter, the current `Request` is passed to it; otherwise it is instantiated with no arguments. The named method is then looked up on the instance.

## Route groups

`Router` supports a `prefix` and shared `middlewares`. Calling `group()` creates and includes a child router, inheriting the parent route context. Mount the top-level router on the app:

```python
from renus.app import App
from renus.router import Router

v1 = Router(prefix='/api/v1', middlewares=[AuthMiddleware])

with v1.group('/items') as items:
    items.get('/{id:id}', ItemController, 'show')
    items.post('', ItemController, 'store')

app = App()
app.include(v1)
```

The `Router` constructor also accepts `subdomain`:

```python
admin = Router(prefix='/api/admin', subdomain='admin')
app.include(admin)
```

Routes resolve by matching the request's subdomain first, then the default domain.

## CRUD shorthand

For controllers with conventional methods, `crud()` registers four routes at once:

```python
r.crud('/items', ItemController)
```

This registers:

| Method | Path             | Handler       |
| ------ | ---------------- | ------------- |
| `GET`    | `/items`         | `index`       |
| `POST`   | `/items`         | `store`       |
| `PUT`    | `/items/{id:id}`| `update`      |
| `DELETE` | `/items/{id:id}`| `delete`      |

Use the optional `func_prefix` to call methods with a prefix, and `mcud()` to register only store/update/delete (methods named `m_store`, `m_update`, `m_delete`).

## How routes are resolved

Each `App` owns a `RouteRegistry` instance, grouped by subdomain and method. Routers hold route definitions until explicitly included in another router or mounted on an app. When a request arrives, the app's registry:

1. Reads the request method and the normalized path from the scope (a trailing `/` is stripped).
2. Rejects unsupported methods and raises on path-traversal attempts (`..` or a null byte).
3. Checks the request's subdomain (validated against the configured `host` app config), then the default domain.
4. Matches the exact (static) path first, then tries the compiled path-parameter regexes in registration order.
5. Builds a route result carrying the resolved arguments (already converted to their typed values), the controller, handler, middlewares, and optional cache TTL.

The registry distinguishes static routes (exact matches, resolved in O(1)) from parameterized routes (matched against compiled regexes). Its matcher is cached and rebuilt lazily when routes are mounted or via `app.registry.clear()`.

You can inspect registered routes:

```python
app = App()
print(app.registry.summary())
```

## Path safety

The `is_safe_path()` check rejects paths containing a null byte or a `..` segment, preventing path traversal outside the application root. Attempts to resolve such a path raise a `RuntimeError`.
