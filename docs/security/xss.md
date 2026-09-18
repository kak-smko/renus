# XSS Protection

Cross-site scripting (XSS) happens when attacker-controlled text is interpreted as HTML or script in a browser. Renus sanitizes parsed request form data by default, but it does not sanitize every value in your application or every response you create.

## Safe request forms

`await request.form()` sanitizes string keys and values recursively before returning a `FormData` object:

```python
@app.post("/profile")
async def profile(request):
    form = await request.form()
    bio = form.get("bio")
    # Use bio as data; it has passed Renus's request sanitizer.
```

The sanitizer also processes nested dictionaries and lists. `None`, booleans, integers, and floats are preserved. `UploadFile` values are not changed.

The sanitizer parses HTML and emits escaped markup rather than executable markup. It blocks or rewrites dangerous elements and attributes. For example, a `script` element is not returned as an executable `<script>` tag, and `javascript:` URLs are rewritten because only `http` and `https` protocols are accepted for `href` and `src`.

The sanitizer's HTML allowlist permits a limited set of tags/attributes, including attributes used by links and images. Allowed markup is still returned escaped (`&lt;...&gt;`), so the result is safe as text rather than a request to render arbitrary HTML.

## Raw request forms

`await request.form_unsafe()` returns parsed values without XSS sanitization:

```python
@app.post("/trusted-parser")
async def trusted_parser(request):
    form = await request.form_unsafe()
    # Sanitize or validate every value before putting it into HTML,
    # JavaScript, a template, a log, or another interpreter.
```

Use `form_unsafe()` only when the next processing step applies an appropriate context-aware policy. Do not pass its values directly into an HTML response.

Request parsing, body limits, and form content types are documented in [`/docs/development/request.md`](/docs/development/request.md).

## Response boundaries

The request sanitizer protects data while it is read from `request.form()`. It does not automatically sanitize:

- route parameters, query parameters, headers, or cookies;
- values read from a database or cache;
- values passed directly to `HtmlResponse` or another response;
- HTML templates or browser-side DOM operations.

`HtmlResponse` is an HTML response; it does not make arbitrary content safe. Prefer `JsonResponse` when returning data:

```python
from renus.response import JsonResponse


@app.get("/search")
async def search(request):
    return JsonResponse({"query": request.query_params.get("q", "")})
```

For HTML, escape at the output context used by your template or browser API. HTML text, an HTML attribute, a URL, JavaScript, and CSS require different encoding rules. Do not rely on one generic transformation for all contexts.

Response types and headers are described in [`/docs/development/response.md`](/docs/development/response.md).

## Cookies and browser behavior

When a response sets a session or other sensitive cookie, configure its browser protections explicitly:

```python
response.set_cookie(
    "session",
    session_token,
    secure=True,
    httponly=True,
    samesite="lax",
)
```

`set_cookie()` supports `secure`, `httponly`, and `samesite` values of `strict`, `lax`, or `none`. These flags reduce the impact of some attacks; they do not replace output encoding, authorization, or CSRF defenses.

## XSS checklist

1. Use `request.form()` unless you have a specific reason to handle raw values.
2. Validate the sanitized data's type, length, and allowed values; sanitization is not validation.
3. Use `JsonResponse` for data APIs.
4. Context-escape values before rendering HTML, attributes, URLs, JavaScript, or CSS.
5. Treat `form_unsafe()` as tainted data until your own sanitizer has processed it.
6. Keep secrets out of HTML, logs, URLs, and client-visible responses.
