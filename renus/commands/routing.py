from __future__ import annotations

import os
import re


def _router_alias(module: str) -> str:
    parts = module.split(".")
    if parts and parts[0] == "app":
        parts.pop(0)
    if parts and parts[0] == "extension":
        parts.pop(0)
    if parts and parts[-1] == "route":
        parts.pop()
    name = re.sub(r"\W+", "_", "_".join(parts)).strip("_")
    return f"{name}_route"


def include_router_in_index(module: str, base_dir: str = "./") -> None:
    """Add an exported router to ``routes/api.py`` for the app factory."""
    routes_index = os.path.join(base_dir, "routes", "api.py")
    os.makedirs(os.path.dirname(routes_index), exist_ok=True)
    if not os.path.exists(routes_index):
        with open(routes_index, "w", encoding="utf-8") as file:
            file.write("from renus.router import Router\n\nrouter = Router()\n")

    alias = _router_alias(module)
    import_line = f"from {module} import router as {alias}"
    include_line = f"router.include({alias})"
    legacy_import = f"import {module}"
    with open(routes_index, "r", encoding="utf-8") as file:
        original_lines = file.readlines()

    lines = [line for line in original_lines if line.strip() != legacy_import]
    route_imports = []
    includes = []
    body = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("from ") and " import router as " in stripped:
            if stripped not in route_imports:
                route_imports.append(stripped)
        elif stripped.startswith("router.include(") and stripped.endswith(")"):
            if stripped not in includes:
                includes.append(stripped)
        else:
            body.append(line.rstrip("\n"))

    if import_line not in route_imports:
        route_imports.append(import_line)
    if include_line not in includes:
        includes.append(include_line)

    content = "\n".join(route_imports)
    body_content = "\n".join(body).strip()
    if "from renus.router import Router" not in body_content.splitlines():
        body_content = "from renus.router import Router" + (
            "\n\n" + body_content if body_content else ""
        )
    if not any(line.startswith("router =") for line in body_content.splitlines()):
        body_content = body_content.rstrip() + "\n\nrouter = Router()"
    content += "\n\n" + body_content.rstrip()
    content += "\n\n" + "\n".join(includes) + "\n"

    if content != "".join(original_lines):
        with open(routes_index, "w", encoding="utf-8") as file:
            file.write(content)


def remove_router_from_index(module: str, app: str, base_dir: str = "./") -> None:
    """Remove a module's router import and include from ``routes/api.py``."""
    routes_index = os.path.join(base_dir, "routes", "api.py")
    if not os.path.exists(routes_index):
        return

    with open(routes_index, "r", encoding="utf-8") as file:
        original = file.readlines()

    import_prefix = f"from {module} import router as "
    aliases = {
        line.strip()[len(import_prefix):]
        for line in original
        if line.strip().startswith(import_prefix)
    }
    lines = [
        line
        for line in original
        if not line.strip().startswith(import_prefix)
        and not any(line.strip() == f"router.include({alias})" for alias in aliases)
    ]
    if lines != original:
        with open(routes_index, "w", encoding="utf-8") as file:
            file.writelines(lines)
