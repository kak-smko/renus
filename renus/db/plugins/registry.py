from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Any

from renus.db.core.adapter import AsyncDatabaseAdapter
from renus.db.core.exceptions import ConfigurationError

__all__ = [
    "adapters",
    "clear_adapters",
    "get_adapter",
    "has_adapter",
    "register_adapter",
    "reset_builtin_adapters",
    "unregister_adapter",
]

_REGISTRY: dict[str, Any] = {}
ENTRY_POINT_GROUPS = ("db.adapters", "renus.db.adapters")

def _ensure_adapter_factory(factory: Any, name: str) -> None:
    """Raise if ``factory`` cannot resolve to an ``AsyncDatabaseAdapter``."""
    if isinstance(factory, AsyncDatabaseAdapter):
        return
    if isinstance(factory, type) and issubclass(factory, AsyncDatabaseAdapter):
        return
    raise ConfigurationError(
        f"Invalid adapter factory for '{name}': {type(factory).__name__}. "
        "Expected an AsyncDatabaseAdapter instance or a subclass."
    )

def register_adapter(name: str, factory: Any) -> None:
    """Register an adapter factory under the given name.

    The factory must be an ``AsyncDatabaseAdapter`` instance or a subclass.
    """
    _ensure_adapter_factory(factory, name)
    _REGISTRY[name.lower()] = factory

def unregister_adapter(name: str) -> None:
    """Remove the adapter registered under the given name."""
    _REGISTRY.pop(name.lower(), None)

def has_adapter(name: str) -> bool:
    """Return whether an adapter with the given name is available."""
    key = name.lower()
    if key in _REGISTRY:
        return True
    try:
        get_adapter(key)
        return True
    except ConfigurationError:
        return False

def get_adapter(name: str) -> Any:
    """Resolve an adapter by name, loading it from entry points or a module path."""
    key = name.strip().lower()
    if key in _REGISTRY:
        return _REGISTRY[key]

    for grp in ENTRY_POINT_GROUPS:
        try:
            for ep in entry_points(group=grp):
                if ep.name.lower() == key:
                    obj = ep.load()
                    _ensure_adapter_factory(obj, key)
                    _REGISTRY[key] = obj
                    return obj
        except ConfigurationError:
            raise
        except Exception:
            pass

    if ":" in name:
        mod_path, class_name = name.split(":", 1)
        try:
            mod = importlib.import_module(mod_path)
            obj = getattr(mod, class_name)
            _ensure_adapter_factory(obj, key)
            _REGISTRY[key] = obj
            return obj
        except Exception as exc:
            raise ConfigurationError(
                f"Failed to import DB adapter '{name}' from module '{mod_path}': {exc}"
            ) from exc

    available = tuple(sorted(_REGISTRY.keys()))
    raise ConfigurationError(
        f"Unknown DB adapter: {name!r}. Available registered adapters: {available}"
    )

def adapters() -> tuple[str, ...]:
    """Return the names of all registered adapters."""
    return tuple(sorted(_REGISTRY.keys()))

def clear_adapters() -> None:
    """Remove all registered adapters."""
    _REGISTRY.clear()

def reset_builtin_adapters() -> None:
    """Reset the registry to only the built-in adapters."""
    clear_adapters()
    try:
        from renus.db.sqlite import SQLiteAdapter

        register_adapter("sqlite", SQLiteAdapter)
    except Exception:
        pass

    try:
        from renus.db.mysql import MySQLAdapter

        register_adapter("mysql", MySQLAdapter)
    except Exception:
        pass

    try:
        from renus.db.mongodb import MongoDBAdapter

        register_adapter("mongodb", MongoDBAdapter)
    except Exception:
        pass
