from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any

from renus.rich import Terminal

def _extract_description_from_file(file_path: Path) -> str | None:
    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "DESCRIPTION":
                        if isinstance(node.value, ast.Constant) and isinstance(
                            node.value.value, str
                        ):
                            return node.value.value
    except Exception:
        pass
    return None

def _get_command_desc(module_path: str, dir_path: Path, custom: bool = False) -> str:
    for entry_file in (dir_path / "run.py", dir_path / "__init__.py"):
        if entry_file.exists():
            desc = _extract_description_from_file(entry_file)
            if desc:
                return f"[custom] {desc}" if custom and not desc.startswith("[custom]") else desc

    for sub in (".run", ""):
        try:
            mod = importlib.import_module(module_path + sub)
            desc = getattr(mod, "DESCRIPTION", None)
            if desc:
                return f"[custom] {desc}" if custom and not str(desc).startswith("[custom]") else str(desc)
            if mod.__doc__:
                return mod.__doc__.strip().split("\n")[0]
        except Exception:
            continue

    name = dir_path.name
    return f"[custom] Run {name} command" if custom else f"Run {name} command"

def discover_commands(project_dir: Path | str | None = None) -> dict[str, str]:
    """Discover available framework and project commands."""
    commands: dict[str, str] = {}

    framework_dir = Path(__file__).parent
    for item in sorted(framework_dir.iterdir()):
        if item.is_dir() and not item.name.startswith(("_", ".")):
            if (item / "run.py").exists() or (item / "__init__.py").exists():
                commands[item.name] = _get_command_desc(f"renus.commands.{item.name}", item)

    proj_path = Path(project_dir) if project_dir else Path.cwd()
    project_commands = proj_path / "commands"
    if project_commands.exists() and project_commands.is_dir():
        for item in sorted(project_commands.iterdir()):
            if item.is_dir() and not item.name.startswith(("_", ".")):
                if (item / "run.py").exists() or (item / "__init__.py").exists():
                    commands[item.name] = _get_command_desc(
                        f"commands.{item.name}", item, custom=True
                    )

    return commands

def Help(commands: dict[str, str] | None = None) -> None:
    """Print the CLI help menu."""
    if commands is None:
        commands = discover_commands()

    print()
    Terminal.cyan.print(Terminal.bold("Renus Framework CLI"))
    Terminal.dim.print("Usage: renus <command> [arguments]\n")

    rows = []
    for name, desc in commands.items():
        rows.append([Terminal.green(name), Terminal.white(desc.strip())])

    Terminal.table(headers=["Command", "Description"]).print(rows)
    print()
