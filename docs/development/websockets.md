# WebSockets

Renus supports server-side WebSockets over ASGI. A WebSocket connection is represented by the `WebSocket` class in `renus/websockets`, which combines the request object (`WebSocket` subclasses `Request`) with a protocol state machine. It exposes helpers for accepting a connection, receiving text/binary/JSON messages, sending replies, iterating over inbound messages, and closing cleanly.

## Registering a WebSocket route

Register a WebSocket handler with the `WS` method. The handler receives the current `WebSocket` as the `ws` argument (injected into the handler arguments during dispatch):

```python
from renus.app import App

app = App()

@app.route('/ws', method='WS')
async def websocket(ws):
    await ws.accept()
    await ws.send_text('Hello, world!')
    await ws.close()
```

The same route can be registered on a standalone `Router` with the fluent `.ws(path, ...)` method:

```python
from renus.router import Router

r = Router()
r.ws('/ws', chat_handler)
```

Handlers may be plain `async` functions or controller methods, and path parameters work as with HTTP routes:

```python
@app.route('/rooms/{name:str}', method='WS')
async def room(ws, name):
    await ws.accept()
    await ws.send_text(f'Welcome to {name}')
    await ws.close()
```

## The connection lifecycle

The server wraps the ASGI `websocket` scope in a `WebSocket` and dispatches the matching route (`serve_websocket` in `renus/app/dispatch.py`). Inside the handler you drive the lifecycle explicitly:

1. **Accept** — call `await ws.accept()`, optionally selecting a subprotocol.
2. **Exchange messages** — receive and send text, bytes, or JSON.
3. **Close** — call `await ws.close(code)` to end the connection.

If no route matches (or the route has no callable handler), the connection is closed with code `1004` automatically.

### Accepting and subprotocols

`accept()` signals the server is ready to begin the message exchange:

```python
await ws.accept()
```

The client may offer one or more subprotocols via the `Sec-WebSocket-Protocol` header. You can list them and select one:

```python
subprotocols = ws.requested_subprotocols   # e.g. ["chat", "superchat"]
await ws.accept(subprotocol='chat')
```

Selecting a subprotocol the client did not offer raises `WebSocketProtocolError`.

### Closing

`close(code=1000)` sends a close frame with the given status code. It is safe to call repeatedly:

```python
await ws.close()                              # normal closure
await ws.close(1008)                          # policy violation
await ws.close(WebSocketCloseCode.NORMAL)     # descriptive alias
```

The `WebSocketCloseCode` enum in `renus/websockets` lists the standard close codes (`NORMAL = 1000`, `PROTOCOL_ERROR = 1002`, `POLICY_VIOLATION = 1008`, …). The `Status` enum in `renus/response` also exposes WebSocket close codes as `Status.WS_1000_NORMAL_CLOSURE`, … .

## Sending messages

| Method | Payload | Description |
| ------ | ------- | ----------- |
| `send_text(data: str)`   | text | Sends a text message. |
| `send_bytes(data: bytes)` | binary | Sends a binary message. |
| `send_json(data, mode='text')` | text or binary | JSON-encodes `data` and sends it as text or binary. |

```python
await ws.send_text('ping')
await ws.send_bytes(b'\x00\xff')
await ws.send_json({'user': 'ada', 'message': 'hi'}, mode='text')
```

`send_json` uses the shared JSON encoder, so non-serializable types (such as `datetime`) are handled consistently with the rest of Renus. Pass `mode='binary'` to send the JSON payload as a binary frame.

## Receiving messages

The receive helpers return the next inbound message and raise `WebSocketDisconnect` when the client disconnects:

| Method | Returns |
| ------ | ------- |
| `receive_text(protect=True)` | `str` |
| `receive_bytes()` | `bytes` |
| `receive_json(protect=True)` | decoded JSON value |

Text and JSON payloads are sanitized for XSS by default. The `protect` flag controls this (`Injection().protect(...)` in `renus/websockets/session.py`); pass `protect=False` to receive raw, unescaped data.

A typical echo loop:

```python
@app.route('/echo', method='WS')
async def echo(ws):
    await ws.accept()
    try:
        while True:
            text = await ws.receive_text()
            await ws.send_text(text)
    except WebSocketDisconnect:
        pass
```

### Iterating over messages

Instead of an explicit loop, use one of the async iterators. They run until the client disconnects and then return:

| Iterator | Yields |
| -------- | ------ |
| `iter_text()` | each message as `str` |
| `iter_bytes()` | each message as `bytes` |
| `iter_json()` | each message decoded as JSON |
| `iter_messages()` / `async for m in ws` | each raw message `dict` |

```python
@app.route('/collect', method='WS')
async def collect(ws):
    await ws.accept()
    messages = [msg async for msg in ws.iter_text()]
    await ws.send_json({'count': len(messages)})
    await ws.close()
```

## Connection state

`WebSocket` tracks the client side and the application side of the connection via the `WebSocketState` enum (`CONNECTING`, `CONNECTED`, `DISCONNECTED`), exposed as `ws.client_state` and `ws.application_state`.

The following read-only properties summarize that state:

| Property | Meaning |
| -------- | ------- |
| `scope`  | The ASGI websocket scope. |
| `client_connected`  | The client side is `CONNECTED`. |
| `application_connected` | The application side is `CONNECTED`. |
| `connected` | Both sides are `CONNECTED`. |

The protocol validates every transition (`WebSocketProtocol` in `renus/websockets/protocol.py`). Invalid operations — such as sending after a close, sending before accept, or receiving after a disconnect — raise `WebSocketProtocolError`.

## Disconnects

When the client disconnects, receive operations raise `WebSocketDisconnect`. The exception carries the close code and an optional reason:

```python
from renus.websockets import WebSocketDisconnect

try:
    text = await ws.receive_text()
except WebSocketDisconnect as exc:
    print('disconnected with code', exc.code)
```

## Middlewares

WebSocket routes use the same middleware chain as HTTP routes. The endpoint sends the messages, and a short-circuiting middleware (one that returns a non-`True` value) closes the connection with code `1003` instead of producing a regular response. See [Middlewares](/docs/development/middlewares.md).

## Message builders

The low-level helpers in `renus/websockets/messages.py` build the ASGI message dicts used by `send_text`, `send_bytes`, `send_json`, `accept`, and `close`. They are re-exported from `renus.websockets` and available if you need to construct messages manually:

```python
from renus.websockets import accept_message, close_message
from renus.websockets import send_text_message, send_bytes_message, send_json_message

accept_message()                                # {'type': 'websocket.accept'}
accept_message(subprotocol='chat')
send_text_message('hi')                         # {'type': 'websocket.send', 'text': 'hi'}
send_bytes_message(b'\x00\x01')                 # {'type': 'websocket.send', 'bytes': ...}
send_json_message({'ok': True}, mode='text')
close_message()                                 # {'type': 'websocket.close', 'code': 1000}
close_message(1008)
```
