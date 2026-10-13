from __future__ import annotations

import os

from renus.commands.routing import include_router_in_index
from renus.commands.app.temp import (
    controller_temp,
    model_temp,
    route_temp,
    route_kit_temp,
    vue_temp,
)
from renus.rich import Terminal
from renus.util import to_camel_case, to_plural

__all__ = ["DESCRIPTION", "add_routes", "add_temp", "to_camel_case", "to_plural"]

DESCRIPTION = "Create New Package."

def _is_kit_extension_installed(base_dir: str = "./") -> bool:
    check_paths = (
        os.path.join(
            base_dir, "app", "extension", "codenus", "kit", "middlewares", "auth.py"
        ),
        os.path.join(
            base_dir, "extension", "codenus", "kit", "middlewares", "auth.py"
        ),
    )
    return any(os.path.exists(p) for p in check_paths)

def add_temp(
    name: str,
    names: str,
    name_camel: str,
    names_camel: str,
    name_db: str,
    folder: list[str],
    base_dir: str = "./",
) -> None:
    """Generate controller, model, route, and Vue templates for a package."""
    pth = os.path.join(base_dir, "app")
    pname = ""
    vname = ""

    if len(folder) > 0:
        pth = os.path.join(pth, *folder)
        pname = ".".join(folder) + "."
        vname = "/" + "/".join(folder) + "/"

    pth = os.path.join(pth, name)
    os.makedirs(pth, exist_ok=True)

    ctrl_code = controller_temp.replace("{name}", pname + name)
    ctrl_code = ctrl_code.replace("{name_camel}", name_camel)
    ctrl_code = ctrl_code.replace("{names_camel}", names_camel)
    with open(os.path.join(pth, "controller.py"), "w", encoding="utf-8") as f:
        f.write(ctrl_code)

    model_code = model_temp.replace("{names_camel}", names_camel)
    model_code = model_code.replace("{name_camel}", name_camel)
    model_code = model_code.replace("{name_db}", name_db)
    with open(os.path.join(pth, "model.py"), "w", encoding="utf-8") as f:
        f.write(model_code)

    view_dir = os.path.join(base_dir, "frontend", "admin", "src", "views", vname.lstrip("/"))
    os.makedirs(view_dir, exist_ok=True)
    vue_code = vue_temp.replace("{name}", name)
    vue_code = vue_code.replace("{names}", names)
    vue_code = vue_code.replace("{folder}", vname.lstrip("/"))
    with open(os.path.join(view_dir, f"{name}.vue"), "w", encoding="utf-8") as f:
        f.write(vue_code)

    use_kit_ext = _is_kit_extension_installed(base_dir=base_dir)
    selected_route_temp = route_kit_temp if use_kit_ext else route_temp

    route_code = selected_route_temp.replace("{name}", pname + name)
    route_code = route_code.replace("{names}", names)
    route_code = route_code.replace("{name_camel}", name_camel)
    route_code = route_code.replace("{folder}", vname.rstrip("/"))
    with open(os.path.join(pth, "route.py"), "w", encoding="utf-8") as f:
        f.write(route_code)

def add_routes(
    name: str,
    names: str,
    name_camel: str,
    folder: list[str],
    base_dir: str = "./",
) -> None:
    """Wire package routes into the backend and frontend router."""
    pname = ""
    vname = ""
    if len(folder) > 0:
        pname = ".".join(folder) + "."
        vname = "/".join(folder) + "/"

    include_router_in_index(f"app.{pname + name}.route", base_dir=base_dir)

    router_js = os.path.join(base_dir, "frontend", "admin", "src", "router", "index.js")
    if os.path.exists(router_js):
        with open(router_js, "r", encoding="utf-8") as f:
            content = f.read()

        import_hook = "/* {{place new import}} */"
        route_hook = "/* {{place new app route}} */"

        new_import = f'{import_hook}\nconst {names} = () => import("../views/{vname}{name}.vue");'
        new_route = f'{route_hook}\n{{ path: "{vname}{names}", name: "{names}", component: {names} }},'

        content = content.replace(import_hook, new_import)
        content = content.replace(route_hook, new_route)

        with open(router_js, "w", encoding="utf-8") as f:
            f.write(content)

def run(args: list[str] | None = None, base_dir: str = "./") -> int:
    """Scaffold a new package and register its routes."""
    if args and len(args) > 0:
        raw_name = args[0].strip().lower()
    else:
        raw_name = input("name (single lowercase): ").strip().lower()

    if not raw_name:
        Terminal.red.print("Error: package name cannot be empty.")
        return 1

    folder = raw_name.split(".")
    name = folder[-1]
    folder = folder[:-1]

    name_camel = to_camel_case(name)
    plural_raw = to_plural(name)
    names = plural_raw[0].lower() + plural_raw[1:] if plural_raw else ""
    names_camel = to_camel_case(plural_raw)
    name_db = name.replace("_", "-")

    add_temp(name, names, name_camel, names_camel, name_db, folder, base_dir=base_dir)
    Terminal.green.print("Templates created.")
    add_routes(name, names, name_camel, folder, base_dir=base_dir)
    Terminal.green.print("Routes created.")
    Terminal.cyan.print(f"Package '{name}' is ready.")
    return 0
