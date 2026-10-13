# Middleware

Onion middleware can inspect a request, stop the chain, or call the next handler. This example checks a bearer token loaded from the environment rather than embedding a credential in source:

```python
import hmac
import os

from renus.app import App
from renus.response import JsonResponse, Status

app = App()


async def require_bearer_token(request, method, res):
    expected = os.environ.get("API_TOKEN")
    if not expected:
        return JsonResponse(
            {"error": "Authentication is not configured"},
            Status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied, expected)
    ):
        return JsonResponse(
            {"error": "Unauthorized"},
            Status.HTTP_401_UNAUTHORIZED,
            headers={"www-authenticate": "Bearer"},
        )

    return await method(**res["args"])


@app.get("/profile", middlewares=[require_bearer_token])
async def profile():
    return JsonResponse({"profile": "available"})
```

Set `API_TOKEN` in the process environment before starting the ASGI server, then send it as an `Authorization: Bearer ...` header. This illustrates token comparison only; a production application should use its established identity provider, validate token expiry and audience, and authorize access to the specific resource.

An onion middleware has the `(request, method, res)` signature and continues by awaiting `method(**res["args"])`. See [Middlewares](../development/middlewares.md) for ordering, router-level registration, and legacy middleware behavior.
