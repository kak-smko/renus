from __future__ import annotations

import importlib
import json
import keyword
import shutil
from pathlib import Path
from typing import Any

from renus.commands.extension import build as extension_build
from renus.commands.extension import run as extension_command
from renus.rich import Terminal

DESCRIPTION = """Manage local extensions without downloading them.
  renus local -new-extension test/blog
  renus local -install
  renus local -update
  renus local -upgrade
  renus local -remove
"""

_EXTENSION_ROOT = "extension"
_LOCK_FILE = "extension/extension-lock.json"


def _normalise_app_name(name: str) -> str:
    """Return a package name in the format used by extension metadata."""
    name = name.strip().strip("/")
    name = name.removesuffix("/install.py")
    if name.startswith(f"{_EXTENSION_ROOT}/"):
        name = name[len(_EXTENSION_ROOT) + 1 :]

    path = Path(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Invalid extension name: {name!r}")
    return "/".join(path.parts)


def _create_extension(app: str, base_dir: str) -> bool:
    """Create a minimal local extension package and its application modules."""
    parts = app.split("/")
    if not all(part.isidentifier() and not keyword.iskeyword(part) for part in parts):
        Terminal.red.print(
            f"Invalid extension name: {app!r}. Use Python identifiers separated by '/'."
        )
        return False

    extension_root = Path(base_dir) / _EXTENSION_ROOT
    target = extension_root / Path(app)
    try:
        if not target.resolve().is_relative_to(extension_root.resolve()):
            Terminal.red.print(f"Invalid extension path: {app!r}.")
            return False
    except OSError as exc:
        Terminal.red.print(f"Could not resolve extension path: {exc}")
        return False

    if target.exists():
        Terminal.yellow.print(f"Extension already exists: {target}")
        return False

    package = f"extension.{app.replace('/', '.')}"
    leaf_name = parts[-1]
    class_name = "".join(
        part[:1].upper() + part[1:]
        for part in leaf_name.split("_")
        if part
    ) or "Extension"
    table_name = f"{'_'.join(parts).lower()}_items"
    files = {
        "install.py": (
            'version = "0.1.0"\n'
            f"name = {leaf_name!r}\n"
            'renus_requires = {"min": "3.0.0", "max": "4.0.0"}\n'
            "dependencies = []\n"
            f"route = {package + '.route'!r}\n"
            "imprt = [\n"
            f"    ('controller', {package + '.controller'!r}, '*'),\n"
            f"    ('model', {package + '.model'!r}, '*'),\n"
            "]\n"
        ),
        "route.py": (
            "from renus.router import Router\n\n"
            f"from app.{package}.controller import {class_name}Controller\n\n\n"
            "router = Router()\n"
            f"router.get(\"/{leaf_name.replace('_', '-')}\", {class_name}Controller, \"index\")\n"
        ),
        "controller.py": (
            "from renus.response import JsonResponse\n\n\n"
            f"class {class_name}Controller:\n"
            "    async def index(self):\n"
            f"        return JsonResponse({{'extension': {app!r}, 'items': []}})\n"
        ),
        "model.py": (
            "from renus.db import DatabaseField, Field, Model\n\n\n"
            f"class {class_name}(Model):\n"
            "    id: int = Field(\n"
            "        database=DatabaseField(primary_key=True, generated=True)\n"
            "    )\n"
            "    title: str\n"
            '    content: str = ""\n\n'
            "    class Meta:\n"
            f"        table = {table_name!r}\n"
        ),
    }

    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        Terminal.red.print(f"Could not create extension '{app}': {exc}")
        return False

    try:
        for filename, content in files.items():
            _ = (target / filename).write_text(content, encoding="utf-8")
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        Terminal.red.print(f"Could not create extension '{app}': {exc}")
        return False

    Terminal.green.print(f"Created extension template: {target}")
    return True


def _local_install_file(app: str, base_dir: str) -> Path:
    return Path(base_dir) / _EXTENSION_ROOT / Path(app) / "install.py"


def _module_name(app: str) -> str:
    return f"extension.{app.replace('/', '.')}"


def _load_lock(base_dir: str) -> dict[str, str]:
    path = Path(base_dir) / _LOCK_FILE
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        Terminal.yellow.print(f"Warning: could not read {path}; starting with an empty lock.")
        return {}

    installed = data.get("installed", {}) if isinstance(data, dict) else {}
    if not isinstance(installed, dict):
        return {}
    return {str(name): str(version) for name, version in installed.items()}


def _write_lock(installed: dict[str, str], base_dir: str) -> None:
    path = Path(base_dir) / _LOCK_FILE
    path.write_text(
        json.dumps({"installed": installed}, indent=2) + "\n",
        encoding="utf-8",
    )


def _discover_local_apps(base_dir: str) -> list[str]:
    """Find every local package containing an extension install.py file."""
    root = Path(base_dir) / _EXTENSION_ROOT
    if not root.is_dir():
        return []

    return sorted(
        install_file.parent.relative_to(root).as_posix()
        for install_file in root.rglob("install.py")
        if install_file.is_file()
    )


def _load_install(app: str, base_dir: str) -> Any | None:
    if not _local_install_file(app, base_dir).is_file():
        Terminal.yellow.print(f"Local extension not found: {app}")
        return None
    return importlib.import_module(_module_name(app) + ".install")


def _install_local(
    app: str,
    installed: dict[str, str],
    mode: str,
    base_dir: str,
    processing: set[str],
) -> str | None:
    """Run Renus' normal extension setup using only local package files."""
    install = _load_install(app, base_dir)
    if install is None:
        return None

    if app in processing:
        Terminal.yellow.print(f"Warning: circular dependency while processing '{app}'.")
        return installed.get(app)

    version = str(getattr(install, "version", "local"))
    if mode == "install" and installed.get(app) == version:
        Terminal.yellow.print(f"'{app}' is already installed locally at version {version}.")
        return version

    processing.add(app)
    if mode != "update" or app not in installed:
        installed[app] = version

    try:
        extension_command.install_app(
            app,
            installed,
            mode=mode,
            base_dir=base_dir,
        )
    except Exception:
        if mode == "install":
            installed.pop(app, None)
        raise
    finally:
        processing.remove(app)

    if mode == "install":
        Terminal.green.print(f"Installed local extension '{app}' version {version}.")
    elif mode == "upgrade":
        Terminal.green.print(f"Upgraded local extension '{app}' to version {version}.")
    else:
        Terminal.blue.print(f"Updated local extension '{app}'.")
    return version


def _remove_local(app: str, installed: dict[str, str], base_dir: str) -> None:
    """Remove generated integration files, but preserve the local source package."""
    install = _load_install(app, base_dir)
    installed.pop(app, None)
    if install is None:
        return

    setup_remove = getattr(install, "remove", None)
    if callable(setup_remove):
        Terminal.cyan.print(f"  Calling remove() for {app}...")
        extension_command._run_awaitable(setup_remove())

    if getattr(install, "route", None):
        extension_build._remove_route(install, app, base_dir=base_dir)
    if getattr(install, "command", None):
        extension_build._remove_command(install, app, base_dir=base_dir)
    if getattr(install, "admin_templates", None):
        try:
            extension_build._remove_admin_templates(app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Admin templates removal error: {exc}")
    if getattr(install, "index_templates", None):
        try:
            extension_build._remove_index_templates(app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Index templates removal error: {exc}")
    if getattr(install, "component_templates", None):
        try:
            extension_build._remove_component_templates(app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Component templates removal error: {exc}")
    if getattr(install, "config", None):
        try:
            extension_build._remove_config(install, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Config removal error: {exc}")

    # This is generated output. Deliberately do not remove extension/<app>.
    generated_dir = Path(base_dir) / "app" / "extension" / Path(app)
    shutil.rmtree(generated_dir, ignore_errors=True)


def run(args: list[str] | None = None) -> int:
    """Install, update, upgrade, or remove local extensions."""
    cmd_args = list(args or [])
    operations = {
        "-install": "install",
        "--install": "install",
        "-update": "update",
        "--update": "update",
        "-upgrade": "upgrade",
        "--upgrade": "upgrade",
        "-remove": "remove",
        "--remove": "remove",
        "-new-extension": "new-extension",
        "--new-extension": "new-extension",
    }

    operation_flags = [arg for arg in cmd_args if arg in operations]
    if len(operation_flags) != 1:
        Terminal.red.print(
            "Usage: renus local -install | -update | -upgrade | -remove"
        )
        return 1

    operation = operations[operation_flags[0]]
    cmd_args.remove(operation_flags[0])
    try:
        requested = [_normalise_app_name(arg) for arg in cmd_args]
    except ValueError as exc:
        Terminal.red.print(str(exc))
        return 1

    if operation == "new-extension":
        if len(requested) != 1:
            Terminal.red.print("Usage: renus local -new-extension <namespace/name>")
            return 1
        return 0 if _create_extension(requested[0], ".") else 1

    base_dir = "."
    installed = _load_lock(base_dir)

    if requested:
        targets = requested
    elif operation == "install":
        targets = _discover_local_apps(base_dir)
    else:
        targets = list(installed)

    if not targets:
        message = (
            "No local extensions found in extension/."
            if operation == "install"
            else "No installed extensions found in extension-lock.json."
        )
        Terminal.yellow.print(message)
        return 0

    original_download = extension_command.download
    processing: set[str] = set()

    def local_download(
        app: str,
        version_spec: str,
        lock: dict[str, str],
        mode: str = "install",
        base_dir: str = "./",
    ) -> str | None:
        """Keep dependency resolution on the local filesystem."""
        del version_spec
        return _install_local(
            _normalise_app_name(app),
            lock,
            mode,
            base_dir,
            processing,
        )

    extension_command.download = local_download
    failed = False
    try:
        for app in targets:
            app = _normalise_app_name(app)
            if operation == "remove":
                _remove_local(app, installed, base_dir)
            else:
                if _install_local(
                    app,
                    installed,
                    operation,
                    base_dir,
                    processing,
                ) is None:
                    failed = True
    finally:
        extension_command.download = original_download

    _write_lock(installed, base_dir)
    if failed:
        return 1

    Terminal.green.print(f"Local extension {operation} completed.")
    return 0
