from __future__ import annotations

import os
import sys

from renus.rich import Terminal

DESCRIPTION = "Run the Renus application server with uvicorn (run dev --reload)."

MODE_DEFAULTS: dict[str, dict[str, object]] = {
    "dev": {"reload": True, "host": "127.0.0.1", "port": 8000},
    "prod": {"reload": False, "host": "0.0.0.0", "port": 8000},
}

_FALSE_FLAGS = {
    "proxy_headers",
    "use_colors",
    "server_header",
    "date_header",
    "ws_ping_interval_disabled",
}

_APP_ALIASES = {"app", "application", "asgi", "wsgi"}

def _default_app_target() -> str:
    for module in ("main", "app"):
        if os.path.isfile(f"{module}.py"):
            return f"{module}:app"
    raise SystemExit(
        "Could not auto-detect an application (expected main.py or app.py).\n"
        "Pass --app <module:app>, or create a Renus App instance."
    )

def _parse_flags(argv: list[str]) -> dict[str, object]:
    flags: dict[str, object] = {}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token.startswith("-"):
            if token.startswith("--no-") and "=" not in token:
                name = token[5:].strip().replace("-", "_")
                flags[name] = False
            elif "=" in token:
                name, value = token[2:].split("=", 1)
                flags[name.replace("-", "_")] = value
            else:
                name = token[2:].replace("-", "_")
                if index + 1 < len(argv) and not argv[index + 1].startswith("-"):
                    flags[name] = argv[index + 1]
                    index += 1
                else:
                    flags[name] = True
        index += 1
    return flags

def run(args: list[str] | None = None) -> int:
    """Serve the app with uvicorn using dev/prod defaults."""
    try:
        import uvicorn
    except ImportError:
        Terminal.red.print(
            "uvicorn is required to run the server. Install it with:\n"
            "    pip install renus[server]   # or: pip install uvicorn"
        )
        return 1

    argv = list(args) if args else []

    mode = "dev"
    rest: list[str] = []
    for token in argv:
        if not token.startswith("-") and token in MODE_DEFAULTS and mode in ("dev",):
            mode = token
        else:
            rest.append(token)

    flags = _parse_flags(rest)

    app_target = flags.pop("app", None)
    if app_target is None:
        app_target = _default_app_target()

    defaults = MODE_DEFAULTS[mode]
    reload_flag = flags.pop("reload", None)
    reload = (
        bool(reload_flag)
        if isinstance(reload_flag, bool)
        else bool(defaults["reload"])
    )
    host = str(flags.pop("host", defaults["host"]))
    raw_port = flags.pop("port", defaults["port"])
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        Terminal.red.print(f"Invalid port: {raw_port!r}")
        return 1

    options: dict[str, object] = {}
    for key, value in flags.items():
        if key in _APP_ALIASES:
            continue
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in ("true", "false"):
                value = lowered == "true"
            elif lowered in ("none", "null"):
                value = None
        elif value is True and key not in _FALSE_FLAGS:
            value = True
        options[key] = value

    Terminal.dim.print(
        f"renus {mode} → uvicorn {app_target} "
        f"(host={host} port={port} reload={reload})"
    )

    sys.path.insert(0, os.getcwd())
    uvicorn.run(app_target, host=host, port=port, reload=reload, **options)
    return 0

__all__ = ["DESCRIPTION", "run"]
