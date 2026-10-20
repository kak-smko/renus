from __future__ import annotations

import argparse
import json

import uvicorn


class UvicornApp:
    """Minimal ASGI application used as the native uvicorn baseline."""

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "/")

        if method != "GET":
            body = b"Method Not Allowed"
            status = 405
            headers = [(b"content-type", b"text/plain; charset=utf-8")]
        elif path == "/plain":
            body = b"Hello, World!"
            status = 200
            headers = [(b"content-type", b"text/plain; charset=utf-8")]
        elif path == "/json":
            body = json.dumps({"message":"Hello, World!"}).encode()
            status = 200
            headers = [(b"content-type", b"application/json")]
        elif path.startswith("/user/") and path.removeprefix("/user/"):
            name = path.removeprefix("/user/")
            body = json.dumps({"name": name}, separators=(",", ":")).encode()
            status = 200
            headers = [(b"content-type", b"application/json")]
        else:
            body = b"Not Found"
            status = 404
            headers = [(b"content-type", b"text/plain; charset=utf-8")]

        headers.append((b"content-length", str(len(body)).encode()))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def build_app() -> UvicornApp:
    return UvicornApp()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the native uvicorn benchmark app")
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
