# Middlewares

Middlewares let you run code on every request, or on a specific route, before the route handler is invoked. They are useful for authentication, authorization, request logging, rate limiting, or rewriting request arguments.

Renus request middlewares are registered on a `Router`, when mounting a router, or on an individual route. They run as part of route dispatch and can either pass the request on (by calling the next handler) or short-circuit it by returning a value of their own.

## Registering middlewares

Middlewares can be attached at the router or route level.

### Router-level

A `Router` can carry middlewares that apply to all of its routes and included child routers. The app can also add middleware when mounting a router:

```python
from renus.router import Router

v1 = Router(middlewares=[AuthMiddleware])
app.include(v1, prefix='/api/v1', middlewares=[TimingMiddleware])
```

### Route-level

Both the `App` decorators and the `Router` fluent methods accept `middlewares` for a single route:

```python
@app.get('/profile', middlewares=[AuthMiddleware])
def profile():
    return JsonResponse({'ok': True})
```

Middlewares are combined in order — mounted/router/include-level lists, then route-level list — and the whole chain runs before the handler. See [Application](/docs/development/app.md) and [Routing](/docs/development/routing.md) for how these register on each API.

## Two middleware signatures

A request middleware is detected by its signature. If it declares **3 or more positional parameters**, it is treated as an **onion** middleware; otherwise it is treated as a **legacy** middleware (`is_onion_middleware` in `renus/router/chain.py`).

### Onion middleware (recommended)

An onion middleware receives `(request, method, res)`:

- `request` — the current `Request` (or `WebSocket`).
- `method` — the next handler in the chain (eventually the route handler).
- `res` — the resolved route data dict, including `res["args"]`.

It decides whether to call the next handler and can wrap it, running code both before and after:

```python
async def timing_middleware(request, method, res):
    start = time.perf_counter()
    resp = await method(**res["args"])
    elapsed = time.perf_counter() - start
    request.state['elapsed'] = elapsed
    return resp
```

Because it receives `method`, the onion style lets you nest middlewares (outer runs before inner and after inner) and intercept the response before it is sent. It can also rewrite `res["args"]` so the handler receives modified arguments.

To **short-circuit** the chain, simply don't call `method()` and return a value instead:

```python
async def auth_middleware(request, method, res):
    if not request.headers.get('authorization'):
        return JsonResponse({'msg': 'Unauthorized'}, Status.HTTP_401_UNAUTHORIZED)
    return await method(**res["args"])
```

### Legacy middleware

A legacy middleware takes only a single `request` argument and returns either `True` to continue the chain, or anything else to short-circuit. It is declared as an async function:

```python
async def gate_middleware(request):
    if not request.headers.get('authorization'):
        return JsonResponse({'msg': 'Unauthorized'}, Status.HTTP_401_UNAUTHORIZED)
    return True
```

The result is awaited at run time. If it is not exactly `True`, it is returned to the client and the rest of the chain is skipped.

## How the chain runs

The middleware chain is executed by `run_middleware_chain(request, middlewares, res, endpoint)` in `renus/router/chain.py`.

- With no middlewares, the endpoint is invoked directly.
- Otherwise, middlewares are wrapped **in reverse order**, so the first middleware in the list is the outermost onion layer.
- Onion middlewares that call `await method(**res["args"])` invoke the next wrapped layer; the innermost call reaches the actual route endpoint.
- Legacy middlewares that return `True` pass control to the next wrapped layer; a non-`True` result stops the chain and becomes the response.

When a route also uses caching, the cache lookup happens inside the endpoint (`build_endpoint` in `renus/app/handlers.py`), so middlewares run around the cached dispatch.

## WebSockets

The same chain applies to WebSocket handlers. The endpoint sends the websocket messages, and a short-circuiting middleware (one that returns a non-`True` value) closes the connection with code `1003` instead of a regular response. See [WebSockets](/docs/development/websockets.md).

## Notes

- Use `res["args"]` to read or rewrite the arguments that will be passed to the handler.
- The `request.state` dictionary (and values on `app.state`) can be used to pass data between a middleware and a handler.
- Where the handler declares a `request` parameter, the current `Request` is injected into `res["args"]["request"]` before the chain runs (`serve_view` in `renus/app/dispatch.py`).
