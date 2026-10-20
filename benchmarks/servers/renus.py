from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from renus.app import App
from renus.response import JsonResponse, TextResponse

async def plain() -> TextResponse:
    return TextResponse("Hello, World!")

async def json() -> JsonResponse:
    return JsonResponse({"message": "Hello, World!"})

async def user(name: str) -> JsonResponse:
    return JsonResponse({"name": name})

def build_app() -> App:
    app = App()
    app.get("/plain")(plain)
    app.get("/json")(json)
    app.get("/user/{name}")(user)
    return app

def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the renus benchmark app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app = build_app()
    app.run(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        loop="uvloop",
        http="httptools",
    )
    sys.exit(0)

if __name__ == "__main__":
    main()
