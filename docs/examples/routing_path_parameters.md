# Routing & Path Parameters

Use a converter when a path segment has a known shape. This complete example shows an integer ID and a multi-segment path:

```python
from renus.app import App
from renus.response import JsonResponse

app = App()


@app.get("/users/{user_id:int}")
async def show_user(user_id):
    return JsonResponse({"id": user_id, "type": type(user_id).__name__})


@app.get("/files/{path:path}")
async def show_file(path):
    return JsonResponse({"path": path})
```

With the app running, try:

```bash
curl http://127.0.0.1:8000/users/17
# {"id":17,"type":"int"}

curl http://127.0.0.1:8000/files/reports/2026/january.csv
# {"path":"reports/2026/january.csv"}
```

The `path` converter intentionally captures slashes, so use it only for routes designed to accept multiple segments; do not treat the captured value as a trusted filesystem path. Other supported converters include `str`, `float`, `bool`, `uuid`, and Renus `id`.

See [Routing](../development/routing.md) for routers, controllers, groups, and route matching behavior.
