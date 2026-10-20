from __future__ import annotations

import argparse
import sys

from sanic import Sanic
from sanic.response import json, text

def build_app() -> Sanic:
    app = Sanic("sanic-benchmark")

    @app.get("/plain")
    async def plain(request):
        return text("Hello, World!")

    @app.get("/json")
    async def json_(request):
        return json({"message": "Hello, World!"})

    @app.get("/user/<name>")
    async def user(request, name):
        return json({"name": name})

    return app

def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Sanic benchmark app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app = build_app()
    app.run(
        host=args.host,
        port=args.port,
        workers=1,
        access_log=False,
        debug=False,
        auto_reload=False,
        single_process=True,
        motd=False,
    )

    sys.exit(0)

if __name__ == "__main__":
    main()
