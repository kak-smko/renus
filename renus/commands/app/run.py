from __future__ import annotations

import asyncio
import importlib
import os
import sys

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


async def _async_add_kit_menu_route(
    route_name: str,
) -> None:
    """Add the generated package to the Codenus Kit admin menu."""
    from renus.db import Database

    menu_model = importlib.import_module(
        "app.extension.codenus.kit.menu.model"
    ).Menu
    get_last_id = importlib.import_module(
        "extension.codenus.kit.menu.service"
    ).last_id

    async with Database() as db:
        repo = db.repository(menu_model)
        admin_menu = await repo.where(menu_model.name == "admin").first()
        if admin_menu is None:
            return

        menu_data = admin_menu.data
        if not isinstance(menu_data, list):
            return
        if any(
            isinstance(item, dict) and item.get("permission") == route_name
            for item in menu_data
        ):
            return

        menu_id = get_last_id(menu_data) + 1
        menu_data.append(
            {
                "id": menu_id,
                "titles": {"en": route_name},
                "permission": route_name,
                "children": [],
                "active": True,
                "to": f'{{"name": "{route_name}"}}',
            }
        )
        await repo.where(menu_model.name == "admin").update({"data": menu_data})


def _add_kit_menu_route(
    base_dir: str,
    route_name: str,
) -> None:
    """Run the optional Kit menu update with the project on the import path."""
    project_dir = os.path.abspath(base_dir)
    added_to_path = project_dir not in sys.path
    if added_to_path:
        sys.path.insert(0, project_dir)
    try:
        asyncio.run(
            _async_add_kit_menu_route(route_name)
        )
    finally:
        if added_to_path:
            sys.path.remove(project_dir)


def add_temp(
    name: str,
    names: str,
    name_camel: str,
    names_camel: str,
    name_db: str,
    folder: list[str],
    base_dir: str = "./",
    soft_delete: bool = True,
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
    soft_delete_controller = ""
    if soft_delete:
        soft_delete_controller = '''
    async def restore(self, id: ID):
        exist = await self.repo.where({name_camel}.id == id).with_deleted().first()
        if exist is None:
            return JsonResponse({"msg": "not_found"}, Status.HTTP_404_NOT_FOUND)
        if not getattr(exist, "is_deleted", False):
            return JsonResponse({"msg": "not_deleted"}, Status.HTTP_400_BAD_REQUEST)
        await self.repo.restore({name_camel}.id == id)
        return JsonResponse({"msg": "restored"})

    async def remove(self, id: ID):
        exist = await self.repo.where({name_camel}.id == id).with_deleted().first()
        if exist is None:
            return JsonResponse({"msg": "not_found"}, Status.HTTP_404_NOT_FOUND)

        await self.repo.hard_delete({name_camel}.id == id)
        return JsonResponse({"msg": "removed"})'''.replace(
            "{name_camel}", name_camel
        )
    ctrl_code = ctrl_code.replace("{soft_delete_controller}", soft_delete_controller)
    with open(os.path.join(pth, "controller.py"), "w", encoding="utf-8") as f:
        f.write(ctrl_code)

    model_code = model_temp.replace("{names_camel}", names_camel)
    model_code = model_code.replace("{name_camel}", name_camel)
    model_code = model_code.replace("{name_db}", name_db)
    model_code = model_code.replace(
        "{soft_delete_meta}", "        soft_delete = True" if soft_delete else ""
    )
    with open(os.path.join(pth, "model.py"), "w", encoding="utf-8") as f:
        f.write(model_code)

    view_dir = os.path.join(base_dir, "frontend", "admin", "src", "views", vname.lstrip("/"))
    os.makedirs(view_dir, exist_ok=True)
    vue_code = vue_temp.replace("{name}", name)
    vue_code = vue_code.replace("{names}", names)
    vue_code = vue_code.replace("{folder}", vname.lstrip("/"))
    vue_code = vue_code.replace(
        "{soft_delete_attribute}", " soft-delete" if soft_delete else ""
    )
    with open(os.path.join(view_dir, f"{name}.vue"), "w", encoding="utf-8") as f:
        f.write(vue_code)

    use_kit_ext = _is_kit_extension_installed(base_dir=base_dir)
    selected_route_temp = route_kit_temp if use_kit_ext else route_temp

    route_code = selected_route_temp.replace("{name}", pname + name)
    route_code = route_code.replace("{names}", names)
    route_code = route_code.replace("{name_camel}", name_camel)
    route_code = route_code.replace("{folder}", vname.rstrip("/"))
    route_code = route_code.replace(
        "{soft_delete_routes}",
        f'admin_router.put("/{names}/restore/{{id:id}}", {name_camel}Controller, "restore")\n'
        f'admin_router.delete("/{names}/remove/{{id:id}}", {name_camel}Controller, "remove")'
        if soft_delete else "",
    )
    route_code = route_code.replace(
        "{soft_delete_kit_routes}",
        f'admin_router.put("/{names}/restore/{{id:id}}", {name_camel}Controller, "restore", middlewares=[PermissionMiddleware("{names}.restore")])\n'
        f'admin_router.delete("/{names}/remove/{{id:id}}", {name_camel}Controller, "remove", middlewares=[PermissionMiddleware("{names}.remove")])'
        if soft_delete else "",
    )
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
    command_args = args or []
    raw_name = command_args[0].strip().lower() if command_args else ""
    if not raw_name:
        raw_name = input("name (single lowercase): ").strip().lower()
    if not raw_name:
        Terminal.red.print("Error: package name cannot be empty.")
        return 1

    soft_delete_option = next(
        (arg for arg in command_args[1:] if arg in ("--soft-delete", "--no-soft-delete")),
        None,
    )
    if soft_delete_option is not None:
        soft_delete = soft_delete_option == "--soft-delete"
    elif sys.stdin.isatty() and sys.stdout.isatty():
        answer = input("Enable soft delete? [Y/n]: ").strip().lower()
        soft_delete = answer not in ("n", "no")
    else:
        soft_delete = True

    folder = raw_name.split(".")
    name = folder[-1]
    folder = folder[:-1]

    name_camel = to_camel_case(name)
    plural_raw = to_plural(name)
    names = plural_raw[0].lower() + plural_raw[1:] if plural_raw else ""
    names_camel = to_camel_case(plural_raw)
    name_db = name.replace("_", "-")

    add_temp(
        name,
        names,
        name_camel,
        names_camel,
        name_db,
        folder,
        base_dir=base_dir,
        soft_delete=soft_delete,
    )
    Terminal.green.print("Templates created.")
    add_routes(name, names, name_camel, folder, base_dir=base_dir)
    Terminal.green.print("Routes created.")

    if _is_kit_extension_installed(base_dir=base_dir):
        try:
            _add_kit_menu_route(
                base_dir,
                names,
            )
        except Exception as exc:
            Terminal.red.print(f"Error: could not add the package to the Kit menu: {exc}")
            return 1

    Terminal.cyan.print(f"Package '{name}' is ready.")
    return 0
