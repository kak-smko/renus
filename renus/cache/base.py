from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from renus.cache.utils import hash_key

class BaseCache(ABC):

    driver: str | None = None

    def __init__(self, prefix: str = "") -> None:
        """Initialize the cache backend with a key prefix.

        Parameters
        ----------
        prefix:
            Optional key prefix namespacing this cache instance.
        """
        self._prefix = prefix

    def _id(self, key) -> str:
        return f"{self._prefix}{hash_key(key)}"

    @abstractmethod
    def put(self, key, value, expire: int = 60):
        """Store a value under ``key`` for ``expire`` seconds.

        Parameters
        ----------
        key:
            Cache key.
        value:
            Value to store.
        expire:
            TTL in seconds (``< 0`` / ``None`` stores forever).
        """
        pass

    @abstractmethod
    def get(self, key, default=None):
        """Return the value for ``key``, or ``default`` if missing/expired."""
        pass

    @abstractmethod
    def increment(self, key, value, expire: int = 60):
        """Add ``value`` to the existing value and return the new total."""
        pass

    @abstractmethod
    def expire(self, key, default=None):
        """Return remaining TTL (seconds) for ``key``, ``-1`` if expired/unset."""
        pass

    @abstractmethod
    def delete(self, key):
        """Delete ``key`` and return ``True`` if it existed."""
        pass

    @abstractmethod
    def delete_expired(self):
        """Remove all expired entries and return the number removed."""
        pass

    async def aput(self, key, value, expire: int = 60):
        """Async variant of :meth:`put`."""
        return await asyncio.to_thread(self.put, key, value, expire)

    async def aget(self, key, default=None):
        """Async variant of :meth:`get`."""
        return await asyncio.to_thread(self.get, key, default)

    async def aincrement(self, key, value, expire: int = 60):
        """Async variant of :meth:`increment`."""
        return await asyncio.to_thread(self.increment, key, value, expire)

    async def aexpire(self, key, default=None):
        """Async variant of :meth:`expire`."""
        return await asyncio.to_thread(self.expire, key, default)

    async def adelete(self, key):
        """Async variant of :meth:`delete`."""
        return await asyncio.to_thread(self.delete, key)

    async def adelete_expired(self):
        """Async variant of :meth:`delete_expired`."""
        return await asyncio.to_thread(self.delete_expired)
