
# Renus

**Renus** is a lightweight ASGI framework/toolkit, which is ideal for building async web services in Python. It is production-ready and designed for large-scale projects while maintaining a lightweight footprint and high performance.

## ✨ Features

- 🚀 **High Performance**: Great overall performance against independent benchmarks.
- 🪶 **Lightweight**: Low-complexity HTTP web framework with few hard dependencies.
- 🔄 **Async Support**: Fully compatible with `asyncio` and `trio` backends.
- 🔌 **WebSocket Support**: Built-in support for WebSockets.
- 🛠️ **Background Tasks**: Handle in-process background tasks easily.
- 🔄 **Lifespan Events**: Manage startup and shutdown events for resource management.
- 📦 **Built-in Utilities**: CORS, GZip, Static Files, Streaming responses, Caching, Cryptography, Scheduling, and more.
- ✅ **Reliable**: 100% test coverage.
- 📝 **Type Safe**: 100% type annotated codebase.

## 📦 Installation

Install Renus using pip:

```bash
pip install renus
```

## 🚀 Quick Start

Here is a simple example to get you started with Renus:

```python
from renus.app import App
from renus.core.response import TextResponse, JsonResponse
from renus.router import Router

# 1. Define route handlers
def home():
    return TextResponse('Hello, world!')

def user(username):
    return JsonResponse({'name': username})

async def websocket(ws):
    await ws.accept()
    await ws.send_text('Hello, world!')
    await ws.close()

# 2. Define lifespan events (startup and shutdown)
async def lifespan(app):
    print('Startup', app)
    yield
    print('Shutdown')

# 3. Setup routing
r = Router()
r.get('/', func=home)
r.get('/user/{username}', func=user)
r.ws('/ws', func=websocket)

# 4. Initialize the app
app = App(lifespan=lifespan)
```

### Running the Application

You can run your application using an ASGI server like `uvicorn`:

```python
# main.py
import uvicorn
from renus.app import App
import routes.index # Import your routes module

app = App()

if __name__ == "__main__":
    uvicorn.run(
        "main:app", 
        host="127.0.0.1", 
        port=4000, 
        reload=True, 
        log_level="info",
        headers=[
            ("X-Frame-Options", 'DENY'),
            ("Access-Control-Allow-Headers", '*'),
            ("Access-Control-Allow-Origin", '*')
        ]
    )
```

Run it with:
```bash
python main.py
```

## 📚 Documentation

For full documentation, advanced features, and API references, please visit the official documentation:
👉 **[Renus Documentation](https://codenus.com/en/renus)**

### Advanced Features
Renus comes packed with advanced features out of the box to help you build complex applications:
- **Caching**: Efficient data caching mechanisms.
- **Lifespan**: Manage application lifecycle events.
- **Cryptography**: Built-in cryptographic utilities.
- **Background Tasks**: Handle long-running tasks in the background.
- **Dependency Injection**: Powerful injection system.
- **Logging**: Integrated logging system.
- **Scheduling**: Schedule tasks to run at specific intervals.
- **Thread Pool**: Manage concurrent operations efficiently.

## 🤝 Contributing

Thank you for your interest in contributing to the Renus framework! We welcome all contributions from the community, whether they're bug reports, feature requests, documentation improvements, or code contributions.

### Coding Standards
- Follow **PEP 8** style guidelines.
- Use **type hints** for all new code (PEP 484).
- Keep lines under **88 characters** (Black's default line length).

### Testing
- Write unit tests for all new features using `pytest`.
- Include docstrings for all public methods and classes.

### Issue Reporting
When reporting bugs or requesting features:
- Check existing issues to avoid duplicates.
- Provide detailed reproduction steps for bugs.
- Include Python version, OS, and framework version.
- For feature requests, explain the use case and benefits.

Please read our [Contributing Guidelines](https://codenus.com/en/renus/3) for more details.

## 📄 License

*BSD 3-Clause License*