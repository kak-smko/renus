# Caching

Renus provides a small caching layer for storing values with a time-to-live (TTL). It supports two backends, **file** (an embedded SQLite database) and **redis**, both behind a common `Cache` facade.

Caching appears in two places in Renus:

- **Route-level response caching** — a `cache` TTL on a `GET`/`HEAD` route caches the full response and replays it on later requests.
- **The `Cache` API** — a general-purpose key/value store you can use anywhere in your application.

## Route-level response caching

Pass a TTL in seconds to the `cache` argument when registering a `GET` (or `HEAD`) route:

```python
from renus.app import App

app = App()

@app.get('/slow-report', cache=60)
async def report():
    ...  # expensive work, run at most once every 60 seconds
```

The same works with the `Router` fluent API:

```python
from renus.router import Router

r = Router()
r.get('/slow-report', None, report, None, 60)
```

Cached responses are keyed by `request.full_path` and stored in the configured cache backend. On a cache hit the stored response is returned and annotated with an `r-cache: ok` header so you can see when a response was served from cache. See [Routing](/docs/development/routing.md) and [Application](/docs/development/app.md) for the full signature of the `cache` argument.

> Route caching only applies to `GET` and `HEAD` methods.

The endpoint-level lookup happens inside `build_endpoint` in `renus/app/handlers.py`, so middlewares still run *around* the cached dispatch. See [Middlewares](/docs/development/middlewares.md).

## Backends

The default driver is `file`. You can select a driver with the `cacheDriver` config value or the `Cache(..., driver=...)` argument.

| Driver | Name | Notes |
| ------ | ---- | ----- |
| `file`  | `"file"`  | Embedded SQLite cache stored on disk. Bundled, no extra dependency. |
| `redis` | `"redis"` | Redis-backed cache. Requires the optional `redis` package. |

## The `Cache` API

Create a `Cache` instance and call `put` / `get`, or use the async variants when working inside an async handler:

```python
from renus.cache import Cache

cache = Cache()

# store for 60 seconds (default TTL)
cache.put('greeting', 'hello')

# read it back; returns default (None) if missing or expired
greeting = cache.get('greeting', 'fallback')
```

`Cache` resolves a backend once and caches the instance. `Cache(prefix, driver)` lets you namespace keys:

```python
shared = Cache('billing:')          # file backend by default
counts = Cache('billing:', 'redis') # same prefix, redis backend
```

### Methods

All methods exist on `Cache` and delegate to the underlying backend. Async variants are available for each and run the operation off the event loop via `asyncio.to_thread`.

| Method | Description |
| ------ | ----------- |
| `put(key, value, expire=60)` | Store `value` under `key` for `expire` seconds. `expire < 0` / `None` stores forever. |
| `get(key, default=None)` | Return the value for `key`, or `default` if missing or expired. |
| `increment(key, value, expire=60)` | Add `value` to the existing value and return the new total. |
| `expire(key, default=None)` | Return the remaining TTL in seconds, or `-1` if the key is unset or has no TTL. |
| `delete(key)` | Delete `key`; returns `True` if it existed. |
| `delete_expired()` | Remove expired entries and return the number removed. A no-op on Redis. |

Async variants: `aput`, `aget`, `aincrement`, `aexpire`, `adelete`, `adelete_expired`.

```python
from renus.cache import Cache

cache = Cache()

@app.get('/hits')
async def hits():
    total = await cache.aincrement('site:hits', 1)
    return JsonResponse({"visits": total})
```

### Selecting a driver

Pass `driver="file"` or `driver="redis"` to `Cache`, or set the `cacheDriver` config key in the `app` config. See [Config](/docs/configuration/config.md) for how to set config values.

```python
from renus.cache import Cache

cache = Cache(driver='redis')
```

### `get_backend`

Gets a backend instance directly for a driver name and prefix:

```python
from renus.cache import get_backend

backend = get_backend('file', 'prefix:')
```

An unknown driver name raises `ValueError` listing the available drivers.

## Caching a function with `cache`

`cache` decorates a function so its result is cached for a number of seconds:

```python
from renus.cache import cache

@cache(300)
def expensive_lookup(product_id):
    ...  # computed once per 300 seconds
```

The cached key is derived from the function's file path, function name, and any string/number/collection arguments passed in. Args that are not hashable-cacheable are ignored when building the key.

## The file backend

The `file` backend stores pickled values in a single SQLite table. It is safe to use across threads and uses WAL mode with `busy_timeout`. `increment` is atomic against concurrency using `BEGIN IMMEDIATE`, retrying briefly if the database is locked.

Its database file path comes from the `cache_file_path` config value (default `storage/cache/cache.sqlite`).

## The redis backend

The `redis` backend requires the optional `redis` package:

```
pip install redis
```

Selecting the `redis` driver without the package installed raises `RuntimeError`. When using Redis, expired keys are cleaned up by Redis itself, so `delete_expired()` is a no-op.

The client uses a shared connection pool configured from the `app` config:

| Config key   | Default       |
| ------------ | ------------- |
| `redis_host` | `localhost`   |
| `redis_port` | `6379`        |
| `redis_db`   | `0`           |

`increment` on Redis is protected by a short-lived lock key with an expiry token to avoid lost updates.

## Keys

Every stored key is namespaced by the prefix and hashed with SHA-3 (`hash_key` in `renus/cache/utils.py`), so keys never collide on the raw string and are safe to use in any backend.
