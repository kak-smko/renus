# First HTTP App

This is a small, complete ASGI application with a text route, a typed path parameter, and a JSON request body.

Create `main.py`:

```python
from renus.app import App
from renus.response import JsonResponse, TextResponse

app = App()


@app.get("/")
async def home():
    return TextResponse("Hello from Renus")


@app.get("/users/{user_id:int}")
async def get_user(user_id):
    return JsonResponse({"id": user_id})


@app.post("/echo")
async def echo(request):
    data = await request.form()
    return JsonResponse({"message": data.get("message", "")})
```

Install the server extra and start Uvicorn from the directory containing `main.py`:

```bash
python -m pip install "renus[server]"
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Try the routes in a second terminal:

```bash
curl http://127.0.0.1:8000/
# Hello from Renus

curl http://127.0.0.1:8000/users/42
# {"id":42}

curl -X POST http://127.0.0.1:8000/echo \
  -H 'content-type: application/json' \
  -d '{"message":"hello"}'
# {"message":"hello"}
```

Renus converts `{user_id:int}` to an integer before calling the handler. `request.form()` parses JSON, URL-encoded, and multipart bodies into form data; strings are XSS-sanitized by default. Use an ASGI server such as Uvicorn to serve the app. See [Quick Start](../starting/quick_start.md) for installation and serving options.
