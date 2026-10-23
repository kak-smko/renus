from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from typing import Any

from renus.commands.extension.build import (
    _add_admin_templates,
    _add_cls,
    _add_command,
    _add_component_templates,
    _add_config,
    _add_imprt,
    _add_index_templates,
    _add_route,
)
from renus.commands.extension.remove import remove, remove_all
from renus.rich import Terminal
from renus.util.codec import json_decode, json_encode
from renus.util.version import get_version

DESCRIPTION = """Install/update/remove extensions.
  renus extension codenus/kit
  renus extension codenus/kit==1.2.*
  renus extension --update codenus/kit
  renus extension --upgrade codenus/kit
  renus extension --remove codenus/kit"""

EXTENSION_CONFIG = "extension/extension.json"
EXTENSION_LOCK = "extension/extension-lock.json"


def _run_awaitable(value: Any) -> None:
    """Resolve a lifecycle hook result from the synchronous CLI.
    """
    if not inspect.isawaitable(value):
        return

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(value)
        return

    error: list[BaseException] = []

    def run_in_thread() -> None:
        try:
            asyncio.run(value)
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=run_in_thread)
    thread.start()
    thread.join()
    if error:
        raise error[0]


def _run_hook(install: Any, name: str, app: str) -> None:
    hook = getattr(install, name, None)
    if hook is None or not callable(hook):
        return
    Terminal.cyan.print(f"  Calling {name}() for {app}...")
    _run_awaitable(hook())


def http_get(url: str, timeout: int = 30) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "renus-extension-installer",
            "Accept": "application/json, */*",
        },
    )
    retries = 2

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.status
                headers = {k.lower(): v for k, v in resp.headers.items()}
                content = resp.read()
                if status_code >= 500 and attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return status_code, headers, content
        except urllib.error.HTTPError as exc:
            if exc.code >= 500 and attempt < retries:
                exc.close()
                time.sleep(0.5 * (attempt + 1))
                continue
            headers = {k.lower(): v for k, v in exc.headers.items()}
            return exc.code, headers, exc.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Network request failed for '{url}': {reason}") from exc

    raise RuntimeError(f"Network request failed for '{url}' after {retries + 1} attempts")

def parse_version_tuple(v: str) -> tuple[int, ...]:
    cleaned = v.strip().lstrip("v")
    parts: list[int] = []
    for seg in cleaned.split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)

def get_available_versions(app: str) -> list[str]:
    versions: list[str] = []
    url = f"https://codenus.com/app/versions/{app}"

    try:
        status, headers, content = http_get(url)
        if status == 200 and content:
            try:
                data = json_decode(content)
                if isinstance(data, list):
                    versions = [str(v) for v in data]
                elif isinstance(data, dict) and "versions" in data:
                    versions = [str(v) for v in data["versions"]]
            except Exception:
                pass

        if not versions and "versions" in headers:
            versions = [v.strip() for v in headers["versions"].split(",") if v.strip()]
    except Exception:
        pass

    return versions

def match_version(spec: str, available_versions: list[str]) -> str:
    spec = spec.strip()

    if not available_versions:
        return "latest" if spec == "*" else spec.rstrip(".*")

    sorted_versions = sorted(available_versions, key=parse_version_tuple, reverse=True)

    if spec in ("*", "", "latest"):
        return sorted_versions[0]

    if spec.endswith(".*"):
        prefix = spec[:-2] + "."
        matching = [v for v in sorted_versions if v.startswith(prefix) or v == spec[:-2]]
        if matching:
            return matching[0]

    if spec in sorted_versions:
        return spec

    for v in sorted_versions:
        if v.startswith(spec):
            return v

    return spec

def is_upgrade(target_version: str, current_version: str) -> bool:
    if not current_version:
        return False
    return parse_version_tuple(target_version) > parse_version_tuple(current_version)


def download(
    app: str,
    version_spec: str,
    installed: dict[str, str],
    mode: str = "install",
    base_dir: str = "./",
) -> str | None:
    available_versions = get_available_versions(app)
    if version_spec.strip().endswith(".*") and not available_versions:
        Terminal.red.print(
            f"Could not resolve version '{version_spec}' for '{app}': no versions available."
        )
        return None
    target_version = match_version(version_spec, available_versions)
    if version_spec.strip().endswith(".*") and "*" in target_version:
        Terminal.red.print(
            f"Could not find a version matching '{version_spec}' for '{app}'."
        )
        return None

    current_installed = installed.get(app)
    effective_mode = mode

    if current_installed:
        if mode == "install" and is_upgrade(target_version, current_installed):
            effective_mode = "upgrade"
            Terminal.cyan.print(
                f"Upgrading '{app}' from {current_installed} to {target_version}..."
            )
        elif mode == "install" and current_installed == target_version:
            Terminal.yellow.print(f"'{app}' is already installed at version {current_installed}.")
            return current_installed

    Terminal.green.print(f"Downloading {app}/{target_version}...")

    url = f"https://codenus.com/app/{app}/{target_version}"
    try:
        status_code, headers, content = http_get(url)
    except Exception as exc:
        Terminal.red.print(f"Download error: {exc}")
        return None

    if status_code != 200:
        detail = content.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        Terminal.red.print(f"Download error: HTTP {status_code}{suffix}")
        return None

    resolved_version = headers.get("version", target_version)
    installed[app] = resolved_version

    dest_dir = os.path.join(base_dir, "extension", app)
    shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(dest_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(BytesIO(content)) as zip_file:
            zip_file.extractall(dest_dir)
    except zipfile.BadZipFile:
        Terminal.red.print("Download error: received invalid zip archive.")
        return None

    install_app(app, installed, mode=effective_mode, base_dir=base_dir)

    if effective_mode == "upgrade":
        Terminal.green.print(
            f"Successfully upgraded '{app}' to version {resolved_version}."
        )
    elif effective_mode == "update":
        Terminal.blue.print(f"Updated '{app}' to version {resolved_version}.")
    else:
        Terminal.green.print(f"Installed '{app}' version {resolved_version}.")

    return resolved_version

def _read_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json_decode(f.read())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

def load_apps(base_dir: str = "./") -> dict[str, str]:
    apps = _read_json(os.path.join(base_dir, EXTENSION_CONFIG)).get("apps", {})
    if not isinstance(apps, dict):
        return {}
    return {str(app): str(ver) for app, ver in apps.items()}

def load_installed(base_dir: str = "./") -> dict[str, str]:
    installed = _read_json(os.path.join(base_dir, EXTENSION_LOCK)).get("installed", {})
    if not isinstance(installed, dict):
        return {}
    return {str(app): str(ver) for app, ver in installed.items()}


def write_lock(installed: dict[str, str], base_dir: str = "./") -> None:

    with open(os.path.join(base_dir, EXTENSION_LOCK), "w", encoding="utf-8") as f:
        f.write(json_encode({"installed": dict(installed)}, indent=True))
        f.write("\n")

def check_version(install: Any, app: str) -> None:
    renus_requires = getattr(install, "renus_requires", None)
    if not renus_requires:
        return

    current_ver = get_version()
    current_tuple = parse_version_tuple(current_ver)

    if "min" in renus_requires:
        min_tuple = parse_version_tuple(renus_requires["min"])
        if current_tuple < min_tuple:
            raise RuntimeError(
                f"{app}: renus version too low. {current_ver} < {renus_requires['min']}"
            )

    if "max" in renus_requires:
        max_tuple = parse_version_tuple(renus_requires["max"])
        if current_tuple >= max_tuple:
            raise RuntimeError(
                f"{app}: renus version too high. {current_ver} >= {renus_requires['max']}"
            )

def install_app(
    app: str,
    installed: dict[str, str],
    mode: str = "install",
    base_dir: str = "./",
) -> None:
    Terminal.cyan.print(f"Configuring extension: {app} (mode: {mode})")
    install: Any = None
    try:
        install = importlib.import_module(f"extension.{app.replace('/', '.')}.install")
    except Exception as exc:
        Terminal.yellow.print(f"Notice: {exc}")
        return

    check_version(install, app)

    if hasattr(install, "dependencies") and install.dependencies:
        Terminal.cyan.print(f"Installing dependencies for '{app}'...")
        for dependency in install.dependencies:
            dep = str(dependency).strip()
            if "==" in dep:
                dep_app, version_spec = dep.split("==", 1)
                dep_app = dep_app.strip()
                version_spec = version_spec.strip() or "*"
            else:
                dep_app, version_spec = dep, "*"
            if dep_app:
                download(
                    dep_app,
                    version_spec,
                    installed,
                    mode=mode,
                    base_dir=base_dir,
                )

    if mode == "update":
        try:
            _run_hook(install, "update", app)
        except Exception as exc:
            Terminal.red.print(f"  Update error: {exc}")
        return

    if hasattr(install, "cls") and install.cls:
        Terminal.dim.print(f"  Registering classes for {app}...")
        try:
            _add_cls(install, app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Failed registering classes: {exc}")

    if hasattr(install, "route") and install.route:
        Terminal.dim.print(f"  Registering routes for {app}...")
        _add_route(install, app, base_dir=base_dir)

    if hasattr(install, "imprt") and install.imprt:
        Terminal.dim.print(f"  Registering imports for {app}...")
        try:
            _add_imprt(install, app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Failed registering imports: {exc}")

    if hasattr(install, "command") and install.command:
        Terminal.dim.print(f"  Registering commands for {app}...")
        try:
            _add_command(install, app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Failed registering commands: {exc}")

    if hasattr(install, "admin_templates") and install.admin_templates:
        Terminal.dim.print(f"  Registering admin templates for {app}...")
        try:
            _add_admin_templates(install, app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Failed registering admin templates: {exc}")

    if hasattr(install, "index_templates") and install.index_templates:
        Terminal.dim.print(f"  Registering index templates for {app}...")
        try:
            _add_index_templates(install, app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Failed registering index templates: {exc}")

    if hasattr(install, "component_templates") and install.component_templates:
        Terminal.dim.print(f"  Registering component templates for {app}...")
        try:
            _add_component_templates(install, app, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Failed registering component templates: {exc}")

    if hasattr(install, "config") and install.config:
        Terminal.dim.print(f"  Registering config for {app}...")
        try:
            _add_config(install, base_dir=base_dir)
        except Exception as exc:
            Terminal.red.print(f"  Failed registering config: {exc}")

    if mode == "upgrade":
        try:
            _run_hook(install, "upgrade", app)
        except Exception as exc:
            Terminal.red.print(f"  Upgrade error: {exc}")
    else:
        try:
            _run_hook(install, "setup", app)
        except Exception as exc:
            Terminal.red.print(f"  Setup error: {exc}")

def install_all(
    apps: dict[str, str],
    installed: dict[str, str],
    mode: str = "install",
    base_dir: str = "./",
) -> bool:
    targets = installed if mode in ("update", "upgrade") else apps
    succeeded = True
    for app, ver in targets.items():
        result = download(
            app,
            "*" if mode in ("update", "upgrade") else ver,
            installed,
            mode=mode,
            base_dir=base_dir,
        )
        if result is None:
            succeeded = False
    return succeeded

def run(args: list[str] | None = None, base_dir: str = "./") -> int:
    """Install, update, upgrade, or remove extensions."""
    Terminal.bold.print("Renus Extension Manager")
    apps = load_apps(base_dir)
    installed = load_installed(base_dir)

    mode = "install"
    is_remove = False

    cmd_args = list(args) if args is not None else []

    if "--update" in cmd_args:
        mode = "update"
        cmd_args.remove("--update")
    if "--upgrade" in cmd_args:
        mode = "upgrade"
        cmd_args.remove("--upgrade")
    if "--remove" in cmd_args:
        is_remove = True
        cmd_args.remove("--remove")

    if is_remove and mode in ("update", "upgrade"):
        Terminal.red.print("Error: cannot combine '--remove' with '--update' or '--upgrade'")
        return 1

    succeeded = True
    if not cmd_args:
        if is_remove:
            remove_all(installed, base_dir=base_dir)
        else:
            succeeded = install_all(apps, installed, mode=mode, base_dir=base_dir)
    else:
        target = cmd_args[0]
        version = "*"
        if "==" in target:
            app_name, version = target.split("==", 1)
        else:
            app_name = target

        if is_remove:
            remove(app_name, installed, base_dir=base_dir)
        elif download(app_name, version, installed, mode=mode, base_dir=base_dir) is None:
            succeeded = False

    write_lock(installed, base_dir=base_dir)
    if not succeeded:
        Terminal.red.print("Operation failed.")
        return 1
    Terminal.green.print("Operation completed.")
    return 0
