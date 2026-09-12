from __future__ import annotations

import threading
from typing import Any

from renus.cache.base import BaseCache
from renus.cache.file import FileCache
from renus.cache.redis import RedisCache
from renus.cache.utils import hash_key
from renus.config import Config

_DRIVERS = {
    "file": FileCache,
    "redis": RedisCache,
}

def get_backend(driver: str, prefix: str) -> BaseCache:
    """Return the cache backend instance for the given driver and prefix.

    Parameters
    ----------
    driver:
        Backend driver name (``"file"`` or ``"redis"``).
    prefix:
        Key prefix namespacing the backend instance.

    Raises
    ------
    ValueError
        If the driver name is unknown.
    """
    klass = _DRIVERS.get((driver or "").lower())
    if klass is None:
        drivers = ", ".join(sorted(_DRIVERS))
        raise ValueError(f"Unknown cache driver: {driver!r}. Available drivers: {drivers}")
    return klass(prefix)

class Cache:

    _instances: dict[tuple[str, str], BaseCache] = {}
    _instance_lock = threading.RLock()

    def __init__(self, prefix: str = "", driver: str | None = None) -> None:
        """Resolve and bind the cache backend.

        Parameters
        ----------
        prefix:
            Optional key prefix namespacing this cache instance.
        driver:
            Backend driver name (``"file"`` or ``"redis"``). Defaults to the
            ``cacheDriver`` config value or ``"file"``.
        """
        self.driver = (driver or Config("app").get("cacheDriver", "file") or "file").lower()
        self._prefix = prefix
        self._backend = self._get_backend(self.driver, prefix)

    @classmethod
    def _get_backend(cls, driver, prefix) -> BaseCache:
        key = (driver, prefix)
        with cls._instance_lock:
            backend = cls._instances.get(key)
            if backend is None:
                backend = get_backend(driver, prefix)
                cls._instances[key] = backend
            return backend

    @classmethod
    def clear_instances(cls) -> None:
        with cls._instance_lock:
            cls._instances.clear()

    @property
    def backend(self) -> BaseCache:
        return self._backend

    def put(self, key, value, expire: int = 60) -> None:
        """Store ``value`` under ``key`` with a TTL of ``expire`` seconds."""
        return self._backend.put(key, value, expire)

    def get(self, key, default=None) -> Any:
        """Return the value for ``key``, or ``default`` if missing/expired."""
        return self._backend.get(key, default)

    def increment(self, key, value, expire: int = 60):
        """Add ``value`` to the existing value and return the new total."""
        return self._backend.increment(key, value, expire)

    def expire(self, key, default=None):
        """Return remaining TTL (seconds) for ``key``; ``-1`` if none."""
        return self._backend.expire(key, default)

    def delete(self, key):
        """Delete ``key`` and return ``True`` if it existed."""
        return self._backend.delete(key)

    def delete_expired(self):
        """Remove all expired entries and return the number removed."""
        return self._backend.delete_expired()

    async def aput(self, key, value, expire: int = 60) -> None:
        """Async variant of :meth:`put`."""
        return await self._backend.aput(key, value, expire)

    async def aget(self, key, default=None) -> Any:
        """Async variant of :meth:`get`."""
        return await self._backend.aget(key, default)

    async def aincrement(self, key, value, expire: int = 60):
        """Async variant of :meth:`increment`."""
        return await self._backend.aincrement(key, value, expire)

    async def aexpire(self, key, default=None):
        """Async variant of :meth:`expire`."""
        return await self._backend.aexpire(key, default)

    async def adelete(self, key):
        """Async variant of :meth:`delete`."""
        return await self._backend.adelete(key)

    async def adelete_expired(self):
        """Async variant of :meth:`delete_expired`."""
        return await self._backend.adelete_expired()

def cache_func(time: int, prefix: str = ""):
    """Decorate a function to cache its result for a set number of seconds.

    Parameters
    ----------
    time:
        Cache TTL in seconds.
    prefix:
        Optional key prefix for the cached entry.
    """

    def dec(func):
        name = func.__name__
        file = func.__code__.co_filename

        def wrapper(*args, **kw):
            k = prefix + file + name
            for i in args:
                if type(i) in [str, int, float, list, dict, tuple, set]:
                    k = k + hash_key(i)

            has = Cache().get(k, "no_cached")
            if has != "no_cached":
                return has

            f = func(*args, **kw)
            Cache().put(k, f, time)
            return f

        return wrapper

    return dec
