from __future__ import annotations

import hashlib
import hmac
import pickle
import threading
from typing import Any

from renus.config import Config

_MAGIC = b"RNSC1"
_DIGEST_SIZE = 32
_HEADER_SIZE = len(_MAGIC) + _DIGEST_SIZE

_key: bytes | None = None
_key_lock = threading.Lock()


def _signing_key() -> bytes:
    """Return the HMAC key for cache payloads.

    Resolution order: the ``cache_secret`` app config value if set, otherwise
    a random key generated once and persisted next to the cache storage so
    multiple processes (and both cache drivers) share the same key.
    """
    global _key
    if _key is not None:
        return _key
    with _key_lock:
        if _key is None:
            secret = Config("app").get("key","123")
            _key = hashlib.sha256(secret.encode("utf-8")).digest()
        return _key


def dumps(value: Any) -> bytes:
    """Serialize ``value`` to a signed pickle payload."""
    payload = pickle.dumps(value, pickle.HIGHEST_PROTOCOL)
    signature = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    return _MAGIC + signature + payload


def loads(blob: bytes | bytearray | memoryview) -> Any:
    """Deserialize a signed cache payload.

    Raises ``ValueError`` for unsigned, malformed, or tampered payloads so
    callers can treat the entry as a cache miss instead of unpickling it.
    """
    if (
        not isinstance(blob, (bytes, bytearray, memoryview))
        or len(blob) < _HEADER_SIZE
        or bytes(blob[: len(_MAGIC)]) != _MAGIC
    ):
        raise ValueError("unsigned or malformed cache entry")
    signature = bytes(blob[len(_MAGIC) : _HEADER_SIZE])
    payload = bytes(blob[_HEADER_SIZE:])
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("cache entry failed signature verification")
    return pickle.loads(payload)
