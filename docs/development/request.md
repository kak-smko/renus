# Request

The `Request` object represents an incoming HTTP request. It is constructed automatically for every request your application handles, and is passed to route handlers that declare a `request` parameter:

```python
@app.get('/whoami')
def whoami(request):
    return JsonResponse({'agent': request.user_agent, 'path': request.full_path})
```

A controller whose `__init__` declares `request` receives the current `Request` too. The `Request` is built from the ASGI `scope` and `receive` callables in `renus/request/request.py`.

## Accessing request data

### Method and path

| Attribute       | Description |
| --------------- | ----------- |
| `request.method`   | The uppercased HTTP method (e.g. `GET`, `POST`). |
| `request.url`      | The full URL including path and query string. |
| `request.full_path`| The full URL including path and query string (alias for `url`). |
| `request.base_path`| Scheme, host and port portion of the URL. |

### Headers, cookies, and query

| Attribute          | Description |
| ------------------ | ----------- |
| `request.headers`  | A lowercase name-to-value mapping of request headers. |
| `request.cookies`  | A name-to-value mapping of parsed request cookies. |
| `request.query_params` | A mapping of parsed query-string parameters. |
| `request.user_agent`   | The `user-agent` header value, or `None`. |

### Client information

| Attribute      | Description |
| -------------- | ----------- |
| `request.client`   | Client host and port from the ASGI scope (a list). |
| `request.ip`       | Client IP. Honors the `ipHeader` app config when set; otherwise uses the client address. |
| `request.subdomain`| Subdomain of the `Host` header, validated against the `host` app config: hosts outside the configured domain yield `None`. Without a configured `host`, this is the first Host label. `None` for bare hosts / IP literals. |

The `ipHeader` value is read from the `config.app` module via `Config("app").get("ipHeader", False)`.

## Reading the body

### `await request.body()`

Returns the full request body as `bytes`. The body is read once and cached; subsequent calls return the cached value. Reading the body enforces the `max_body_size` app config (default 10 MB), raising `RuntimeError("Request body too large")` if the limit is exceeded.

### `await request.stream()`

Yields the body as an async stream of `bytes` chunks. It can only be consumed once — a second pass raises `RuntimeError("Stream consumed")`. If a client disconnects mid-stream, `ClientDisconnect` is raised.

## Parsing form data

### `await request.form()`

Parses the body based on the `Content-Type` header and returns a `FormData` object for every content type:

- `multipart/form-data` — text fields and `UploadFile` objects for uploaded files.
- `application/x-www-form-urlencoded` — URL-encoded form fields.
- `JSON / otherwise` — decoded from JSON (empty when the body is empty or not decodable JSON).

All three produce a `FormData` instance. Before returning it, `form()` sanitizes each item against XSS (excluding `UploadFile` values), so string keys and values are cleaned — see [XSS Protection](/docs/security/xss.md).

### `await request.form_unsafe()`

Like `form()`, it returns a `FormData` instance, but without applying XSS sanitization. Use this only when you handle sanitization yourself.

### Encrypted bodies

If the request carries an `encrypted` header set to `1`, the body is decrypted before parsing. Decryption uses the configured request cryptor and falls back to the `real-type` header to decide whether the decrypted payload is JSON or URL-encoded. An attempt to decrypt without a configured cryptor raises a `ValueError`. See [Encryption](/docs/security/encryption.md).

## Dynamic attributes and state

Every `Request` carries a `state` dictionary. In addition, `Request.__getattr__` resolves any missing attribute:

1. First from the application's `app.state` (the `app` object is available at `request.state["app"]`).
2. Then from `request.state` itself.

If neither holds the name, an `AttributeError` is raised. This is how values placed on `app.state` — for example a database connection under `app.state["db"]` — are exposed as `request.db` inside handlers.

## Handling client disconnects

`ClientDisconnect` (in `renus/request/exceptions.py`) is raised when a client disconnects while you are reading the request stream. Catch it to clean up resources and avoid writing to a closed connection.

## Request limits

Request parsing is guarded by configurable limits read from `Config("app")`:

| Setting               | Default            | Guarded operation               |
| --------------------- | ------------------ | ------------------------------- |
| `max_body_size`       | `10 * 1024 * 1024` | Body size (10 MB)               |
| `max_headers`         | `100`              | Number of headers               |
| `max_headers_size`    | `8192`             | Single header size              |
| `max_cookies`         | `50`               | Number of cookies               |
| `max_cookies_size`    | `4096`             | Cookie header size              |
| `max_query_size`      | `1024`             | Query-string length             |

Exceeding most limits raises a `RuntimeError`; these settings let you tune how much request data your application accepts.
