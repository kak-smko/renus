# Requests & Responses

A handler gets the current request by declaring a `request` parameter. This example accepts a JSON body, checks a required value, and returns an explicit status and JSON response:

```python
from renus.app import App
from renus.response import JsonResponse, Status

app = App()


@app.post("/search")
async def search(request):
    data = await request.form()
    query = data.get("query", "")
    if not isinstance(query, str) or not query.strip():
        return JsonResponse(
            {"error": "A non-empty query is required"},
            Status.HTTP_400_BAD_REQUEST,
        )
    return JsonResponse({"query": query.strip()})
```

Send JSON with an explicit content type:

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{"query":"renus"}'
# {"query":"renus"}
```

`request.form()` supports JSON, URL-encoded, and multipart bodies and returns `FormData`; strings are sanitized by default. Use `await request.body()` when you need the raw bytes, and avoid consuming `request.stream()` more than once. Choose a response class that matches the output: `TextResponse`, `HtmlResponse`, `JsonResponse`, `RedirectResponse`, `FileResponse`, or `StreamingResponse`.

See [Request](../development/request.md) and [Response](../development/response.md) for body limits, uploads, headers, cookies, and response options.
