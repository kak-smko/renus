from __future__ import annotations

import os
import re


def _router_alias(module: str) -> str:
    name = re.sub(r"\W+", "_", module).strip("_")
    return f"_included_router_{name}"


def include_router_in_index(module: str, base_dir: str = "./") -> None:
    """Add an exported router to ``routes/index.py`` for the app factory."""
    routes_index = os.path.join(base_dir, "routes", "index.py")
    os.makedirs(os.path.dirname(routes_index), exist_ok=True)
    if not os.path.exists(routes_index):
        with open(routes_index, "w", encoding="utf-8") as file:
            file.write("from renus.router import Router\n\nrouter = Router()\n")

    alias = _router_alias(module)
    import_line = f"from {module} import router as {alias}"
    include_line = f"router.include({alias})"
    legacy_import = f"import {module}"
    with open(routes_index, "r", encoding="utf-8") as file:
        lines = file.readlines()

    original = "".join(lines)
    lines = [line for line in lines if line.strip() != legacy_import]
    content = "".join(lines)
    additions = []
    if "from renus.router import Router" not in content:
        additions.append("from renus.router import Router")
    if not any(line.startswith("router =") for line in content.splitlines()):
        additions.append("router = Router()")
    if import_line not in content:
        additions.append(import_line)
    if include_line not in content:
        additions.append(include_line)

    if additions or original != content:
        if additions:
            content = content.rstrip() + "\n\n" + "\n".join(additions) + "\n"
        with open(routes_index, "w", encoding="utf-8") as file:
            file.write(content)


def remove_router_from_index(module: str, base_dir: str = "./") -> None:
    """Remove a module's router import and include from ``routes.index``."""
    routes_index = os.path.join(base_dir, "routes", "index.py")
    if not os.path.exists(routes_index):
        return

    alias = _router_alias(module)
    lines_to_remove = {
        f"from {module} import router as {alias}",
        f"router.include({alias})",
    }
    with open(routes_index, "r", encoding="utf-8") as file:
        original = file.readlines()
    lines = [line for line in original if line.strip() not in lines_to_remove]
    if lines != original:
        with open(routes_index, "w", encoding="utf-8") as file:
            file.writelines(lines)
