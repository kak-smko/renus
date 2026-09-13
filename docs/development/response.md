# Response

Response objects represent what your application sends back to the client. Every response is a subclass of the base `Response` class, which renders the body, builds the HTTP headers, and streams the result over the ASGI interface. All response types are exported from `renus.response`:

```python
from renus.response import (
    Response,
    TextResponse,
    HtmlResponse,
    JsonResponse,
    JsonResponseRedirect,
    RedirectResponse,
    StreamingResponse,
    FileResponse,
    PrivateResponse,
    Status,
)
```

Route handlers can return any `Response` instance (often `async`). If a handler returns a value that is not a `Response`, the dispatcher wraps it in a `TextResponse` automatically (`serve_result` in `renus/app/dispatch.py`), so a handler returning a plain string still works.

## The base `Response` class

It is constructed from a body `content`, a `status_code`, optional `headers`, a `media_type`, an optional `background` task, and an optional `cryptor` for body encryption.

| Argument      | Description |
| ------------- | ----------- |
| `content`     | Body content rendered into bytes. |
| `status_code` | HTTP status code, a `Status` member (default `HTTP_200_OK`). |
| `headers`     | Optional mapping of initial response headers. |
| `media_type`  | Response media type; defaults to the subclass `media_type`. |
| `background`  | Optional task to run after the response is sent. |
| `cryptor`     | Optional callable used to encrypt the response body. |

Class attributes:

| Attribute     | Default      | Description |
| ------------- | ------------ | ----------- |
| `media_type`  | `text/html`  | Fallback `Content-Type`. |
| `charset`     | `utf-8`      | Encoding used to render the body. |
| `cryptor`     | `None`       | Cryptor used to encrypt the body when set. |

### How a response is sent

When called (`await response(request, scope, receive, send)`), the base `Response`:

1. Optionally encrypts the body with the configured cryptor, setting `encrypted=1`, a `real-type` header with the original media type, and `content-type: application/octet-stream`.
2. Gzips the body if the client sends `gzip` in `Accept-Encoding` and the body is larger than `GZIP_MIN_LENGTH` (500 bytes). Otherwise `content-encoding: none` is set.
3. Adds `content-length` and sends the `http.response.start` and `http.response.body` ASGI messages.
4. Runs the `background` task, if any, after the body is sent.

### Headers and cookies

Use `set_cookie()` to set a cookie and `delete_cookie()` to expire one:

```python
async def login(request):
    response = JsonResponse({'ok': True})
    response.set_cookie('session', 'abc123', httponly=True, samesite='lax')
    return response
```

`set_cookie()` arguments: `key`, `value`, optional `max_age`, `expires`, `path` (default `/`), `domain`, `secure`, `httponly`, and `samesite`. `samesite` must be `strict`, `lax`, or `none`.

`delete_cookie(key, path='/', domain=None)` expires a cookie by setting `expires=0` and `max-age=0`.

## Text and HTML responses

`renus/response/text.py` provides `TextResponse` and `HtmlResponse`, which default to `text/plain` and `text/html` respectively. `TextResponse` stringifies its content:

```python
from renus.response import TextResponse, HtmlResponse

@app.get('/')
async def home():
    return TextResponse('Hello, world!')
```

## JSON responses

`renus/response/json.py` provides `JsonResponse`, which serializes its content to JSON bytes via `dumps_bytes` (bytes content is passed through unchanged):

```python
from renus.response import JsonResponse

@app.get('/user/{name}')
async def user(name):
    return JsonResponse({'name': name, 'hits': [1, 2, 3]})
```

### `JsonResponseRedirect`

A JSON response that carries a redirect location. It builds the body as `{"location": <url>}` and defaults to status `HTTP_307_TEMPORARY_REDIRECT`:

```python
from renus.response import JsonResponseRedirect

return JsonResponseRedirect('/next')
```

## Redirect responses

`renus/response/redirects.py` provides `RedirectResponse`, which sets the `Location` header to the given URL and defaults to `HTTP_307_TEMPORARY_REDIRECT`:

```python
from renus.response import RedirectResponse, Status

return RedirectResponse('/login', status_code=Status.HTTP_302_FOUND)
```

## Streaming responses

`renus/response/streaming.py` provides `StreamingResponse`, which streams a body from an async iterable (or a sync iterable, run in a thread pool):

```python
from renus.response import StreamingResponse
from renus.datastructures import Background

async def numbers():
    for i in range(100):
        yield f'{i}\n'

@app.get('/count')
async def count():
    return StreamingResponse(numbers(), media_type='text/plain')
```

`StreamingResponse` also watches for client disconnects, cancelling the stream early. Set `zipped=True` to gzip chunks when the client accepts it. A `background` task runs after the stream finishes.

## File responses

`renus/response/file.py` provides `FileResponse`, which streams a file from disk in 4096-byte chunks. The MIME type is guessed from the filename; an explicit `media_type` overrides it.

```python
from renus.response import FileResponse

@app.get('/download')
async def download():
    return FileResponse('static/report.pdf', filename='report.pdf')
```

Key behaviors:

- `filename` sets the `Content-Disposition` attachment header.
- Stat-derived headers `content-length`, `last-modified`, and an `etag` are added automatically.
- `zipped=True` (the default) compresses the file with gzip when the client accepts it.
- A `HEAD` request (detected via the `method` argument) sends only headers.
- A missing or non-regular file raises `FileResponseError`.
- `on_end` is a callback invoked after the file is sent; `background` runs after that.

## Private responses

`renus/response/private.py` provides `PrivateResponse`, which serves a privately stored URL through a tokenized path. In `render()` it generates a random 50-character token, stores it in the cache, and serves the body as `/storage/private/<token>/<url>`:

```python
from renus.response import PrivateResponse

@app.get('/private')
async def serve():
    return PrivateResponse('doc.pdf')
```

## Status codes

`renus/response/status.py` defines the `Status` enum, which includes a full set of HTTP status codes (`Status.HTTP_200_OK`, `Status.HTTP_404_NOT_FOUND`, …) and WebSocket close codes (`Status.WS_1000_NORMAL_CLOSURE`, …). Pass a `Status` member wherever a `status_code` is expected:

```python
from renus.response import TextResponse, Status

return TextResponse('Not found', Status.HTTP_404_NOT_FOUND)
```

## Gzip helpers

`renus/response/gzip.py` exposes `GzipStreamer`, a streaming gzip compressor, and the constant `GZIP_MIN_LENGTH` (500 bytes). Responses use it internally; you generally call it only when building custom streaming responses.

## Errors and aborting

`renus/response/exceptions.py` provides helpers for raising HTTP errors:

```python
from renus.response import abort, abort_if, abort_unless, HTTPException
```

- `HTTPException(detail, status_code=HTTP_400_BAD_REQUEST)` — raised to signal an HTTP error. A string `detail` is wrapped as `{"msg": detail}`.
- `abort(msg, status_code=400)` — raises `HTTPException`.
- `abort_if(condition, msg, status_code=400)` — raises only when `condition` is true.
- `abort_unless(condition, msg, status_code=400)` — raises only when `condition` is false.

