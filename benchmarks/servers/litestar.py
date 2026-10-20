from __future__ import annotations

import argparse

import uvicorn
from litestar import Litestar, get
from litestar.response import Response

@get("/plain")
async def plain() -> Response:
    return Response(b"Hello, World!", media_type="text/plain")

@get("/json")
async def json_() -> Response:
    return Response({"message": "Hello, World!"}, media_type="application/json")

@get("/user/{name:str}")
async def user(name: str) -> dict[str, str]:
    return {"name": name}

def build_app() -> Litestar:
    return Litestar([plain, json_, user])

def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Litestar benchmark app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(
        build_app(),
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
        loop="uvloop",
        http="httptools",
    )

if __name__ == "__main__":
    main()
