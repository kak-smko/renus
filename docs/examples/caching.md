# Caching

Use route caching for responses that are public and do not vary by user. Use the `Cache` API for individual values:

```python
from renus.app import App
from renus.cache import Cache
from renus.response import JsonResponse

app = App()
cache = Cache(prefix="example:")


@app.get("/public-report", cache=60)
async def public_report():
    return JsonResponse({"status": "generated"})


@app.get("/visits")
async def visits():
    total = await cache.aincrement("site:visits", 1, expire=60)
    return JsonResponse({"visits_in_current_ttl": total})
```

`cache=60` stores the route response for 60 seconds. In the current implementation the route-cache key is `request.path`; query parameters are not included. Do not use this route cache for personalized or authorization-dependent responses, or where query parameters change the result. The visit counter's `expire=60` also means it is a short-lived count, not a durable all-time total.

The default cache backend is file-based; Redis is available with the `redis` optional dependency and configuration. See [Caching](../development/caching.md) for backend setup, expiration, and cache operations.
