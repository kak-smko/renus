# Quick Start

This guide walks you through creating and running your first **Renus** application. It assumes you have already installed Renus — if not, see the [Installation](/docs/starting/installation.md) guide first.

## Your first app

Create a file named `main.py` with the following content:

```python
from renus.app import App
from renus.response import TextResponse, JsonResponse

# 1. Initialize the app first
app = App()

# 2. Register routes with decorators
@app.get('/')
def home():
    return TextResponse('Hello, world!')

@app.get('/user/{username}')
def user(username):
    return JsonResponse({'name': username})

# 3. WebSocket routes use @app.route with method="WS"
@app.route('/ws', method='WS')
async def websocket(ws):
    await ws.accept()
    await ws.send_text('Hello, world!')
    await ws.close()
```

Let's break down what each part does.

### Route handlers

Renus is a function- and class-based framework. Handlers can be plain functions or `async` functions, and they return a response object. Here two plain handlers return a `TextResponse` and a `JsonResponse`, while an `async` handler manages a WebSocket connection.

### Routing with decorators

The `App` exposes decorators that register a route when you decorate a handler:

- `@app.get(path)` registers a `GET` route.
- `@app.post(path)`, `@app.put(path)`, and `@app.delete(path)` register the matching methods.
- `@app.route(path, method='...')` handles any method, including `WS` for WebSockets, `HEAD`, and `OPTIONS`.
- Dynamic segments use `{name}` (optionally typed, e.g. `{id:id}`).

The `App` also exposes `middlewares` and `cache` options on these decorators, and the `Router` class provides an equivalent fluent API if you prefer it.

## Running the application

There are two ways to serve your app — with `app.run()` or with an external ASGI server such as `uvicorn`.

### Using `app.run()`

Renus ships a built-in runner that starts `uvicorn` for you:

```python
# main.py
from renus.app import App

app = App()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4000, reload=True)
```

Run it with:

```bash
python main.py
```

### Using uvicorn directly

Alternatively, install `uvicorn` (`pip install renus[server]`) and point it at the app object:

```bash
uvicorn main:app --host 127.0.0.1 --port 4000 --reload
```

Both approaches serve the same application object on `http://127.0.0.1:4000`.

## Verifying it works

Once the server is running, open your browser or use `curl`:

```bash
curl http://127.0.0.1:4000/
# Hello, world!

curl http://127.0.0.1:4000/user/renus
# {"name":"renus"}
```

The WebSocket endpoint at `/ws` is available for any WebSocket client. When the server is shut down cleanly, you'll see the `Shutdown` message printed by the lifespan handler.

## Next steps

- Understand how a full project is laid out in [Project Structure](/docs/starting/project_structure.md).
- Learn about routes, parameters, and middleware in [Routing](/docs/development/routing.md) and [Middlewares](/docs/development/middlewares.md).
- Explore responses and streaming in [Response](/docs/development/response.md).
