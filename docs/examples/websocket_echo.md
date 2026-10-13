# WebSocket Echo

This route accepts a WebSocket connection and echoes each text message. Save it as `main.py`:

```python
from renus.app import App
from renus.websockets import WebSocketDisconnect

app = App()


@app.route("/echo", method="WS")
async def echo(ws):
    await ws.accept()
    try:
        async for message in ws.iter_text():
            await ws.send_text(message)
    except WebSocketDisconnect:
        pass
```

Install and run an ASGI server with WebSocket support:

```bash
python -m pip install "renus[server]"
uvicorn main:app --host 127.0.0.1 --port 8000
```

Connect with a WebSocket client to `ws://127.0.0.1:8000/echo`, send a text message, and the server sends the same text back. Accept the connection before sending. Validate and authorize clients before trusting their messages; this echo example does neither.

See [WebSockets](../development/websockets.md) for binary and JSON messages, close codes, and connection state.
