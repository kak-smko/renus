from __future__ import annotations

import importlib
import os
import shutil
from typing import Any

from renus.commands.extension.build import (
    _remove_admin_templates,
    _remove_command,
    _remove_component_templates,
    _remove_config,
    _remove_index_templates,
    _remove_route,
)
from renus.rich import Terminal

def remove_all(installed: dict[str, str], base_dir: str = "./") -> None:
    items = list(installed.copy().keys())
    items.reverse()
    for app in items:
        remove(app, installed, base_dir=base_dir)

def remove(app: str, installed: dict[str, str], base_dir: str = "./") -> None:
    Terminal.cyan.print(f"Removing extension: {app}")
    installed.pop(app, None)

    install: Any = None
    try:
        install = importlib.import_module(f"extension.{app.replace('/', '.')}.install")
    except Exception as exc:
        Terminal.yellow.print(f"   Notice: {exc}")

    if install is not None and hasattr(install, "setup_remove"):
        Terminal.dim.print(f"   Running setup_remove for {app}...")
        try:
            install.setup_remove()
        except Exception as exc:
            Terminal.red.print(f"   Setup remove error: {exc}")

    if install is not None and hasattr(install, "route"):
        Terminal.dim.print(f"   Removing route for {app}...")
        _remove_route(install, app, base_dir=base_dir)

    if install is not None and hasattr(install, "command"):
        Terminal.dim.print(f"   Removing command for {app}...")
        _remove_command(install, app, base_dir=base_dir)

    if install is not None and hasattr(install, "admin_templates"):
        Terminal.dim.print(f"   Removing admin templates for {app}...")
        try:
            _remove_admin_templates(app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"   Admin templates removal error: {exc}")

    if install is not None and hasattr(install, "index_templates"):
        Terminal.dim.print(f"   Removing index templates for {app}...")
        try:
            _remove_index_templates(app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"   Index templates removal error: {exc}")

    if install is not None and hasattr(install, "component_templates"):
        Terminal.dim.print(f"   Removing component templates for {app}...")
        try:
            _remove_component_templates(app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"   Component templates removal error: {exc}")

    if install is not None and hasattr(install, "config"):
        Terminal.dim.print(f"   Removing config for {app}...")
        try:
            _remove_config(install, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"   Config removal error: {exc}")

    Terminal.dim.print(f"   Cleaning folder for {app}...")
    app_ext_dir = os.path.join(base_dir, "app", "extension", app)
    ext_dir = os.path.join(base_dir, "extension", app)
    if os.path.exists(app_ext_dir):
        shutil.rmtree(app_ext_dir, ignore_errors=True)
    if os.path.exists(ext_dir):
        shutil.rmtree(ext_dir, ignore_errors=True)
