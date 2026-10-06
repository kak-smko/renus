from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from renus.cache.base import BaseCache
from renus.cache.signing import dumps as _signed_dumps
from renus.cache.signing import loads as _signed_loads
from renus.config import Config


_MAX_BUSY_RETRIES = 3

_conn = None
_conn_lock = threading.RLock()
_db_lock = threading.RLock()

class FileCache(BaseCache):

    driver = "file"

    def __init__(self, prefix: str = "") -> None:
        """Initialize the file (SQLite) cache backend.

        Parameters
        ----------
        prefix:
            Optional key prefix namespacing this cache instance.
        """
        super().__init__(prefix)
        self._conn = None

    async def connect(self):
        """Open the shared SQLite cache connection if needed."""
        self._conn = _get_connection()
        return self

    async def disconnect(self):
        """Close the shared SQLite cache connection.

        The connection is shared by all file-cache instances in this process,
        so it is released only when the cache registry is shut down.
        """
        global _conn
        with _conn_lock:
            if _conn is not None:
                _conn.close()
                _conn = None
        self._conn = None

    def _connection(self):
        if self._conn is None:
            self._conn = _get_connection()
        return self._conn

    def put(self, key, value, expire: int = 60):
        """Store ``value`` under ``key`` with a TTL of ``expire`` seconds."""
        expires = -1.0 if expire is None or expire < 0 else time.time() + expire
        blob = _signed_dumps(value)
        with _db_lock:
            self._connection().execute(
                "INSERT INTO entries(key, value, expires) VALUES(?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires=excluded.expires",
                (self._id(key), blob, expires),
            )
            self._connection().commit()

    def get(self, key, default=None):
        """Return the value for ``key``, or ``default`` if missing/expired."""
        rid = self._id(key)
        with _db_lock:
            row = self._connection().execute(
                "SELECT value, expires FROM entries WHERE key=?", (rid,)
            ).fetchone()
        if row is None:
            return default
        blob, expires = row
        if expires != -1 and expires < time.time():
            self.delete(key)
            return default
        try:
            return _signed_loads(blob)
        except ValueError:
            self.delete(key)
            return default

    def increment(self, key, value, expire: int = 60):
        """Add ``value`` to the existing value and return the new total."""
        rid = self._id(key)
        expires = -1.0 if expire is None or expire < 0 else time.time() + expire

        for attempt in range(_MAX_BUSY_RETRIES + 1):
            try:
                with _db_lock:
                    self._connection().execute("BEGIN IMMEDIATE")
                    new = value
                    try:
                        row = self._connection().execute(
                            "SELECT value FROM entries WHERE key=?", (rid,)
                        ).fetchone()
                        if row is not None:
                            try:
                                new = _signed_loads(row[0]) + value
                            except ValueError:
                                new = value
                        self._connection().execute(
                            "INSERT INTO entries(key, value, expires) VALUES(?, ?, ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires=excluded.expires",
                            (rid, _signed_dumps(new), expires),
                        )
                        self._connection().commit()
                    except BaseException:
                        self._connection().rollback()
                        raise
                return new
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc) or attempt == _MAX_BUSY_RETRIES:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def expire(self, key, default=None):
        """Return remaining TTL (seconds) for ``key``; ``-1`` if none."""
        rid = self._id(key)
        with _db_lock:
            row = self._connection().execute(
                "SELECT expires FROM entries WHERE key=?", (rid,)
            ).fetchone()
        if row is None:
            return -1
        expires = row[0]
        if expires == -1:
            return -1
        return max(-1, int(expires - time.time()))

    def delete(self, key):
        """Delete ``key`` and return ``True`` if it existed."""
        rid = self._id(key)
        with _db_lock:
            cur = self._connection().execute("DELETE FROM entries WHERE key=?", (rid,))
            self._connection().commit()
            return cur.rowcount > 0

    def delete_expired(self):
        """Remove all expired entries and return the number removed."""
        with _db_lock:
            cur = self._connection().execute(
                "DELETE FROM entries WHERE expires != -1 AND expires < ?",
                (time.time(),),
            )
            self._connection().commit()
        from renus.log import Log

        removed = cur.rowcount
        Log().info(f"delete_expired (file) success: {removed} entries")
        return removed

def _get_connection() -> sqlite3.Connection:
    global _conn
    with _conn_lock:
        if _conn is None:
            path = Path(Config("app").get("cache_file_path", "storage/cache/cache.sqlite"))
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS entries ("
                "key TEXT PRIMARY KEY, "
                "value BLOB NOT NULL, "
                "expires REAL NOT NULL)"
            )
            conn.commit()
            _conn = conn
        return _conn
