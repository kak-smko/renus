from __future__ import annotations

import asyncio
import pickle
import threading
import time
import uuid

from renus.cache.base import BaseCache
from renus.config import Config


try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None

class RedisCache(BaseCache):

    driver = "redis"

    def __init__(self, prefix: str = "") -> None:
        """Initialize the Redis cache backend.

        Parameters
        ----------
        prefix:
            Optional key prefix namespacing this cache instance.
        """
        super().__init__(prefix)
        if _redis_lib is None:
            raise RuntimeError(
                "The 'redis' cache driver requires the 'redis' package. "
                "Install it with: pip install redis"
            )
        self._rd = _get_client()

    async def connect(self):
        """Validate the Redis connection during application startup."""
        if self._rd is None:
            self._rd = _get_client()
        await asyncio.to_thread(self._rd.ping)
        return self

    async def disconnect(self):
        """Release the shared Redis connection pool."""
        disconnect = getattr(self._rd, "close", None)
        if disconnect is not None:
            await asyncio.to_thread(disconnect)
        global _pool
        with _pool_lock:
            if _pool is not None:
                disconnect_pool = getattr(_pool, "disconnect", None)
                if disconnect_pool is not None:
                    await asyncio.to_thread(disconnect_pool)
                _pool = None
        self._rd = None

    def _client(self):
        if self._rd is None:
            self._rd = _get_client()
        return self._rd

    def put(self, key, value, expire: int = 60):
        """Store ``value`` under ``key`` with a TTL of ``expire`` seconds."""
        client = self._client()
        rid = self._id(key)
        blob = pickle.dumps(value, pickle.HIGHEST_PROTOCOL)
        if expire is None or expire < 0:
            client.set(rid, blob)
        else:
            client.set(rid, blob, ex=expire)

    def get(self, key, default=None):
        """Return the value for ``key``, or ``default`` if missing."""
        client = self._client()
        rid = self._id(key)
        raw = client.get(rid)
        return default if raw is None else pickle.loads(raw)

    def increment(self, key, value, expire: int = 60):
        """Add ``value`` to the existing value and return the new total."""
        client = self._client()
        rid = self._id(key)
        token = self._acquire_lock(rid)
        try:
            raw = client.get(rid)
            new = value if raw is None else pickle.loads(raw) + value
            blob = pickle.dumps(new, pickle.HIGHEST_PROTOCOL)
            if expire is None or expire < 0:
                client.set(rid, blob)
            else:
                client.set(rid, blob, ex=expire)
            return new
        finally:
            self._release_lock(rid, token)

    def _acquire_lock(self, key: str, ttl_ms: int = 10000, timeout: float = 10.0):
        lock_key = f"{key}:lock"
        token = uuid.uuid4().hex
        deadline = time.time() + timeout
        while time.time() < deadline:
            acquired = self._client().set(lock_key, token, nx=True, px=ttl_ms)
            if acquired:
                return token
            time.sleep(0.01)
        raise TimeoutError(f"Could not acquire cache lock for key {key!r}")

    def _release_lock(self, key: str, token: str) -> None:
        lock_key = f"{key}:lock"
        client = self._client()
        if client.get(lock_key) == token:
            client.delete(lock_key)

    def expire(self, key, default=None):
        """Return remaining TTL (seconds) for ``key``; ``-1`` if none."""
        ttl = self._client().ttl(self._id(key))
        return -1 if ttl is None or ttl < 0 else ttl

    def delete(self, key):
        """Delete ``key`` and return ``True`` if it existed."""
        return self._client().delete(self._id(key))

    def delete_expired(self):
        """No-op for Redis: expired keys are handled by Redis TTL."""
        
        return 0

_pool = None
_pool_lock = threading.RLock()

def _get_client():
    global _pool
    conf = Config("app")
    with _pool_lock:
        if _pool is None:
            _pool = _redis_lib.ConnectionPool(
                host=conf.get("redis_host", "localhost"),
                port=conf.get("redis_port", 6379),
                db=conf.get("redis_db", 0),
                decode_responses=False,
            )
        return _redis_lib.Redis(connection_pool=_pool)
