from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/plain")
    async def plain() -> PlainTextResponse:
        return PlainTextResponse("Hello, World!")

    @app.get("/json")
    async def json() -> JSONResponse:
        return JSONResponse({"message": "Hello, World!"})

    @app.get("/user/{name}")
    async def user(name: str) -> JSONResponse:
        return JSONResponse({"name": name})

    return app

def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the FastAPI benchmark app")
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
