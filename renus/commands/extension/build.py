from __future__ import annotations

import os
import shutil
from typing import Any

def _add_cls(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "cls", None):
        target_dir = os.path.join(base_dir, "app", "extension", app)
        os.makedirs(target_dir, exist_ok=True)
        for item in install.cls:
            file_path = os.path.join(target_dir, f"{item[0]}.py")
            with open(file_path, "a", encoding="utf-8") as file:
                content = f"from {item[1]} import {item[2]}\n\nclass {item[3]}({item[2]}):\n    pass\n"
                file.write(content)

def _add_imprt(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "imprt", None):
        target_dir = os.path.join(base_dir, "app", "extension", app)
        os.makedirs(target_dir, exist_ok=True)
        for item in install.imprt:
            file_path = os.path.join(target_dir, f"{item[0]}.py")
            with open(file_path, "a", encoding="utf-8") as file:
                file.write(f"from {item[1]} import {item[2]}\n")

def _add_route(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "route", None):
        target_dir = os.path.join(base_dir, "app", "extension", app)
        os.makedirs(target_dir, exist_ok=True)
        with open(os.path.join(target_dir, "route.py"), "w", encoding="utf-8") as file:
            file.write(f"import {install.route}\n")

        routes_index = os.path.join(base_dir, "routes", "index.py")
        if os.path.exists(routes_index):
            with open(routes_index, "r", encoding="utf-8") as file:
                content = file.read()
            route_import = f"import app.extension.{app.replace('/', '.')}.route\n"
            if route_import not in content:
                content = route_import + content
                with open(routes_index, "w", encoding="utf-8") as b:
                    b.write(content)

def _remove_route(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "route", None):
        routes_index = os.path.join(base_dir, "routes", "index.py")
        if os.path.exists(routes_index):
            with open(routes_index, "r", encoding="utf-8") as file:
                content = file.read()
            route_import = f"import app.extension.{app.replace('/', '.')}.route\n"
            content = content.replace(route_import, "")
            with open(routes_index, "w", encoding="utf-8") as b:
                b.write(content)

def _add_command(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "command", None):
        name = app.replace("/", "_")
        dest = os.path.join(base_dir, "commands", name)
        shutil.copytree(install.command, dest, dirs_exist_ok=True)

def _remove_command(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "command", None):
        name = app.replace("/", "_")
        dest = os.path.join(base_dir, "commands", name)
        if os.path.exists(dest):
            shutil.rmtree(dest)

def _add_admin_templates(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "admin_templates", None):
        name = app.replace("/", "_")
        dest = os.path.join(base_dir, "frontend", "admin", "src", "extension", app)
        shutil.copytree(install.admin_templates, dest, dirs_exist_ok=True)

        router_js = os.path.join(base_dir, "frontend", "admin", "src", "router", "index.js")
        if os.path.exists(router_js):
            with open(router_js, "r", encoding="utf-8") as file:
                content = file.read()
            import_stmt = f"import {name}_routes from '@/extension/{app}/route.js'\n"
            if import_stmt not in content:
                content = import_stmt + content
            content = content.replace(
                "/* {{place new route}} */",
                f"/* {{place new route}} */\n...{name}_routes,",
            )
            with open(router_js, "w", encoding="utf-8") as b:
                b.write(content)

def _remove_admin_templates(app: str, base_dir: str = "./") -> None:
    name = app.replace("/", "_")
    target = os.path.join(base_dir, "frontend", "admin", "src", "extension", app)
    if os.path.exists(target):
        shutil.rmtree(target)

    router_js = os.path.join(base_dir, "frontend", "admin", "src", "router", "index.js")
    if os.path.exists(router_js):
        with open(router_js, "r", encoding="utf-8") as file:
            content = file.read()
        content = content.replace(f"import {name}_routes from '@/extension/{app}/route.js'\n", "")
        content = content.replace(f"...{name}_routes,", "")
        with open(router_js, "w", encoding="utf-8") as b:
            b.write(content)

def _add_index_templates(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "index_templates", None):
        name = app.replace("/", "_")
        dest = os.path.join(base_dir, "frontend", "index", "src", "extension", app)
        shutil.copytree(install.index_templates, dest, dirs_exist_ok=True)

        router_js = os.path.join(base_dir, "frontend", "index", "src", "router", "index.js")
        if os.path.exists(router_js):
            with open(router_js, "r", encoding="utf-8") as file:
                content = file.read()
            import_stmt = f"import {name}_routes from '@/extension/{app}/route.js'\n"
            if import_stmt not in content:
                content = import_stmt + content
            content = content.replace(
                "/* {{place new route}} */",
                f"/* {{place new route}} */\n...{name}_routes,",
            )
            with open(router_js, "w", encoding="utf-8") as b:
                b.write(content)

def _remove_index_templates(app: str, base_dir: str = "./") -> None:
    name = app.replace("/", "_")
    target = os.path.join(base_dir, "frontend", "index", "src", "extension", app)
    if os.path.exists(target):
        shutil.rmtree(target)

    router_js = os.path.join(base_dir, "frontend", "index", "src", "router", "index.js")
    if os.path.exists(router_js):
        with open(router_js, "r", encoding="utf-8") as file:
            content = file.read()
        content = content.replace(f"import {name}_routes from '@/extension/{app}/route.js'\n", "")
        content = content.replace(f"...{name}_routes,", "")
        with open(router_js, "w", encoding="utf-8") as b:
            b.write(content)

def _add_component_templates(install: Any, app: str, base_dir: str = "./") -> None:
    if getattr(install, "component_templates", None):
        dest1 = os.path.join(base_dir, "frontend", "index", "src", "components", app)
        dest2 = os.path.join(base_dir, "frontend", "admin", "src", "components", app)
        shutil.copytree(install.component_templates, dest1, dirs_exist_ok=True)
        shutil.copytree(install.component_templates, dest2, dirs_exist_ok=True)

def _remove_component_templates(app: str, base_dir: str = "./") -> None:
    dest1 = os.path.join(base_dir, "frontend", "index", "src", "components", app)
    dest2 = os.path.join(base_dir, "frontend", "admin", "src", "components", app)
    if os.path.exists(dest1):
        shutil.rmtree(dest1)
    if os.path.exists(dest2):
        shutil.rmtree(dest2)

def _add_config(install: Any, base_dir: str = "./") -> None:
    if getattr(install, "config", None):
        config_dir = os.path.join(base_dir, "config")
        os.makedirs(config_dir, exist_ok=True)
        target = os.path.join(config_dir, f"{install.config[0]}.py")
        with open(target, "w", encoding="utf-8") as b:
            with open(install.config[1], "r", encoding="utf-8") as src:
                b.write(src.read())

def _remove_config(install: Any, base_dir: str = "./") -> None:
    if getattr(install, "config", None):
        target = os.path.join(base_dir, "config", f"{install.config[0]}.py")
        if os.path.exists(target):
            os.remove(target)
