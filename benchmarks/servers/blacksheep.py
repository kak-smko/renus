from __future__ import annotations

import argparse

import uvicorn
from blacksheep.server import Application
from blacksheep.server.responses import json, text

def build_app() -> Application:
    app = Application()
    router = app.router

    async def plain():
        return text("Hello, World!")

    async def json_():
        return json({"message": "Hello, World!"})

    async def user(request):
        name = request.route_values.get("name", "")
        return json({"name": name})

    router.add_get("/plain", plain)
    router.add_get("/json", json_)
    router.add_get("/user/{name}", user)

    return app

def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the BlackSheep benchmark app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="warning",access_log=False,
    loop="uvloop",
    http="httptools",)

if __name__ == "__main__":
    main()
