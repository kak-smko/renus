from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, ClassVar, Mapping, Optional

logger = logging.getLogger("renus.config")

_MISSING = object()

def _load_module(name: str) -> Any:
    try:
        return importlib.import_module(f"config.{name}")
    except Exception as exc:
        logger.debug("Config module 'config.%s' not available: %s", name, exc)
        return {}

def _traverse(obj: Any, parts: tuple[str, ...]) -> Any:
    current = obj
    for part in parts:
        try:
            current = getattr(current, part)
        except AttributeError:
            return _MISSING
    return current

class Config:
    """A lazy-loaded, cached accessor for a named config module."""

    _cache: ClassVar[dict[str, Any]] = {}
    _lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, name: str) -> None:
        """Create a config accessor bound to the given module name.

        Parameters
        ----------
        name:
            Dot-separated module name under the ``config`` package.
        """
        self.name: str = name
        self.loaded: Any = self._resolve(name)

    @classmethod
    def _resolve(cls, name: str) -> Any:
        loaded = cls._cache.get(name, _MISSING)
        if loaded is not _MISSING:
            return loaded

        with cls._lock:
            loaded = cls._cache.get(name, _MISSING)
            if loaded is _MISSING:
                loaded = _load_module(name)
                cls._cache[name] = loaded
            return loaded

    def get(self, name: str, *default: Any) -> Any:
        """Return a nested value by dotted path, or ``default`` if missing."""
        value = _traverse(self.loaded, tuple(name.split(".")))

        if value is _MISSING:
            if default:
                return default[0]
            return None

        return value

    def __getattr__(self, name: str) -> Any:
        """Resolve a top-level config entry as an attribute."""
        value = _traverse(self.loaded, (name,))
        if value is _MISSING:
            raise AttributeError(
                f"{self.name!r} config has no attribute {name!r}"
            )
        return value

    def __getitem__(self, name: str) -> Any:
        """Resolve a config value by dotted-path item access."""
        value = _traverse(self.loaded, tuple(name.split(".")))
        if value is _MISSING:
            raise KeyError(name)
        return value

    def items(self) -> Optional[Mapping[str, Any]]:
        """Return the underlying config as a mapping, if possible."""
        return _as_mapping(self.loaded)

    def snapshot(self) -> dict[str, Any]:
        """Return a plain dict copy of the loaded config."""
        mapping = _as_mapping(self.loaded)
        return dict(mapping) if mapping is not None else {}

def _as_mapping(obj: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(obj, Mapping):
        return obj
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return None
