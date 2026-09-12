from __future__ import annotations

import difflib
import importlib
import inspect
import os
import sys
from typing import Any

from renus.commands.base import BaseCommand
from renus.rich import Terminal

def get_version() -> str:
    """Return the installed Renus version string."""
    try:
        import renus

        if hasattr(renus, "__version__") and renus.__version__:
            return str(renus.__version__)
    except Exception:
        pass

    try:
        from importlib.metadata import version

        return version("renus")
    except Exception:
        return "2.7.1"

def find_command(name: str) -> Any:
    """Locate and return the command module for a given name."""
    for mod_path in (f"commands.{name}.run", f"commands.{name}"):
        try:
            return importlib.import_module(mod_path)
        except ModuleNotFoundError as exc:

            if exc.name in (
                mod_path,
                f"commands.{name}",
                f"commands.{name}.run",
                "commands",
            ):
                continue
            raise

    for mod_path in (f"renus.commands.{name}.run", f"renus.commands.{name}"):
        try:
            return importlib.import_module(mod_path)
        except ModuleNotFoundError as exc:
            if exc.name in (mod_path, f"renus.commands.{name}", f"renus.commands.{name}.run"):
                continue
            raise

    return None

def execute_handler(handler: Any, args: list[str] | None) -> int:
    """Run a command handler with arguments and return the exit code."""
    if isinstance(handler, type) and issubclass(handler, BaseCommand):
        instance = handler()
        res = instance.run(args)
        return int(res) if isinstance(res, int) else 0

    if inspect.ismodule(handler) and hasattr(handler, "Command"):
        cmd_cls = getattr(handler, "Command")
        if isinstance(cmd_cls, type) and issubclass(cmd_cls, BaseCommand):
            instance = cmd_cls()
            res = instance.run(args)
            return int(res) if isinstance(res, int) else 0

    run_func = getattr(handler, "run", None) if not callable(handler) else handler
    if run_func is None:
        raise AttributeError(f"Command '{getattr(handler, '__name__', handler)}' does not define a 'run' method.")

    sig = inspect.signature(run_func)
    num_params = len(sig.parameters)

    if num_params == 0:
        res = run_func()
    else:
        first_param = next(iter(sig.parameters.values()))
        if args is not None or first_param.default is inspect.Parameter.empty:
            res = run_func(args)
        else:
            res = run_func()

    return int(res) if isinstance(res, int) else 0

def run(argv: list[str] | None = None) -> int:
    """Dispatch a CLI command from argv and return the exit code."""
    args = sys.argv if argv is None else argv

    if len(args) < 2:
        from renus.commands.help import Help

        Help()
        return 0

    command_name = args[1]

    if command_name in ("--help", "-h", "help"):
        from renus.commands.help import Help

        Help()
        return 0

    if command_name in ("--version", "-v", "version"):
        Terminal.cyan.print(f"renus {get_version()}")
        return 0

    try:
        handler = find_command(command_name)
    except Exception as exc:
        Terminal.red.print(f"Error loading command '{command_name}': {exc}")
        return 1

    if handler is None:
        from renus.commands.help import Help, discover_commands

        Terminal.red.print(f"Error: Command '{command_name}' not found.")

        all_commands = list(discover_commands().keys())
        matches = difflib.get_close_matches(command_name, all_commands, n=1, cutoff=0.6)
        if matches:
            Terminal.green.print(f"Did you mean: {matches[0]}?")

        print("Run 'renus' without arguments to see available commands.\n")
        Help()
        return 1

    cmd_args = args[2:] if len(args) > 2 else None

    try:
        return execute_handler(handler, cmd_args)
    except Exception as exc:
        Terminal.red.print(f"Error running '{command_name}': {exc}")
        return 1

def main(argv: list[str] | None = None) -> None:
    """Run the CLI and exit on a nonzero return code."""
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    exit_code = run(argv)
    if argv is None and exit_code != 0:
        sys.exit(exit_code)
