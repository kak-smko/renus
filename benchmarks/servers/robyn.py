from __future__ import annotations

import argparse
import logging

from robyn import Response, Robyn, jsonify

logging.getLogger("robyn.logger").setLevel(logging.WARNING)

def build_app() -> Robyn:
    app = Robyn(__file__)

    @app.get("/plain")
    def plain():
        return Response(status_code=200, headers={"Content-Type": "text/plain"}, description="Hello, World!")

    @app.get("/json")
    def json_():
        return jsonify({"message": "Hello, World!"})

    @app.get("/user/:name")
    def user(request):
        name = request.path_params.get("name", "")
        return jsonify({"name": name})

    return app

def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Robyn benchmark app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app = build_app()
    app.start(host=args.host, port=args.port, _check_port=False)
    import sys

    sys.exit(0)

if __name__ == "__main__":
    main()
