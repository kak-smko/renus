from __future__ import annotations

import hashlib
import hmac
import pickle

import pytest

from renus.cache import Cache, FileCache, RedisCache
from renus.cache import signing as signing_module
from renus.config.config import Config
from renus.request import Request

# --------------------------------------------------------------------------
# Shared fixtures / helpers
# --------------------------------------------------------------------------


def _patch_config(monkeypatch, **values) -> None:
    """Patch ``Config.get`` so named keys return ``values`` and everything
    else resolves to its declared default (mirrors a project without a
    ``config`` package, i.e. the insecure default deployment)."""

    def fake_get(self, name, *default):
        if name in values:
            return values[name]
        return default[0] if default else None

    monkeypatch.setattr(Config, "get", fake_get)
    monkeypatch.setattr(Config, "_cache", {})


@pytest.fixture(autouse=True)
def isolated_cache_env(tmp_path, monkeypatch):
    """Fresh SQLite cache db, empty backend registry and a reset signing key
    for every test (the signing key is a module global in renus.cache.signing)."""

    from renus.cache import file as file_module

    db_path = tmp_path / "cache.sqlite"
    _patch_config(monkeypatch, cache_file_path=str(db_path))
    monkeypatch.setattr(file_module, "_conn", None)
    monkeypatch.setattr(signing_module, "_key", None)
    Cache.clear_instances()
    yield db_path
    Cache.clear_instances()


@pytest.fixture
def redis_cache(monkeypatch):
    fake_data = {}

    class _FakeRedis:
        data = fake_data

        def ping(self):
            return True

        def close(self):
            return None

        def set(self, key, value, ex=None, nx=False, px=None):
            if not nx:
                self.data[key] = value if px is not None else (value, ex)
                return True
            if key in self.data:
                return False
            self.data[key] = value
            return True

        def get(self, key):
            entry = self.data.get(key)
            if entry is None:
                return None
            return entry[0] if isinstance(entry, tuple) else entry

        def ttl(self, key):
            if key not in self.data:
                return -2
            return self.data[key][1]

        def delete(self, key):
            return 1 if self.data.pop(key, None) is not None else 0

    monkeypatch.setattr("renus.cache.redis._redis_lib", object())
    monkeypatch.setattr("renus.cache.redis._get_client", lambda: _FakeRedis())
    return RedisCache()


class _PickleRCECanary:
    """``__reduce__`` returning a builtin call: unpickling executes it.

    Using ``print`` keeps the proof-of-concept harmless while proving that
    a verified cache payload yields arbitrary code execution on load.
    """

    def __reduce__(self):
        return print, ("CACHE_RCE_CANARY",)


def _default_signing_key() -> bytes:
    """The HMAC key derived from the hardcoded default config secret."""
    return hashlib.sha256(b"123").digest()


def _forge_blob(value, key: bytes | None = None) -> bytes:
    """Build a cache blob whose signature verifies under ``key``."""
    key = key if key is not None else _default_signing_key()
    payload = pickle.dumps(value, pickle.HIGHEST_PROTOCOL)
    signature = hmac.new(key, payload, hashlib.sha256).digest()
    return signing_module._MAGIC + signature + payload


def _rce_blob() -> bytes:
    return _forge_blob(_PickleRCECanary())


def _request(
    header: str | None = None,
    value: str = "",
    path: str = "/me",
    query: bytes = b"",
    host: str = "testserver",
) -> Request:
    headers = [(b"host", host.encode())]
    if header is not None:
        headers.append((header.encode(), value.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "scheme": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query,
        "headers": headers,
        "client": ("203.0.113.7", 12345),
        "server": ("127.0.0.1", 8000),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _db_row(backend: FileCache, key: str):
    row = backend._connection().execute(
        "SELECT value, expires FROM entries WHERE key=?", (backend._id(key),)
    ).fetchone()
    return row


# ==========================================================================
# A. LIVE VULNERABILITY DEMONSTRATIONS (pass today = the flaw is present)
# ==========================================================================


# ==========================================================================
# B. VERIFIED-SECURE BEHAVIORS (must keep working)
# ==========================================================================


class TestSignatureVerification:
    """Signed-payload integrity must hold for tampering an attacker can do
    without the signing key: bit flips, truncation, magic/Header stripping,
    and cross-key replay."""

    def test_signature_region_tamper_is_rejected_and_purged(self):
        fc = FileCache()
        fc.put("k", {"a": 1}, expire=60)
        value, expires = _db_row(fc, "k")
        blob = bytearray(value)
        blob[10] ^= 0xFF  # inside the HMAC signature (bytes 5..37)
        fc._connection().execute(
            "UPDATE entries SET value=? WHERE key=?", (bytes(blob), fc._id("k"))
        )
        fc._connection().commit()

        assert fc.get("k") is None
        assert _db_row(fc, "k") is None  # purged, not replayed forever

    def test_zeroed_signature_is_rejected(self):
        fc = FileCache()
        fc.put("k", "v", expire=60)
        value, _ = _db_row(fc, "k")
        blob = signing_module._MAGIC + b"\x00" * 32 + value[37:]
        fc._connection().execute(
            "UPDATE entries SET value=? WHERE key=?", (blob, fc._id("k"))
        )
        fc._connection().commit()

        assert fc.get("k") is None

    def test_truncated_blob_is_rejected_without_raising(self):
        fc = FileCache()
        fc.put("k", "v", expire=60)
        fc._connection().execute(
            "UPDATE entries SET value=? WHERE key=?",
            (signing_module._MAGIC + b"\x00" * 10, fc._id("k")),
        )
        fc._connection().commit()

        assert fc.get("k") is None

    def test_wrong_magic_is_rejected(self):
        fc = FileCache()
        fc.put("k", "v", expire=60)
        value, _ = _db_row(fc, "k")
        blob = b"XRNS1" + value[5:]
        fc._connection().execute(
            "UPDATE entries SET value=? WHERE key=?", (blob, fc._id("k"))
        )
        fc._connection().commit()

        assert fc.get("k") is None

    def test_valid_pickle_without_signature_is_rejected(self):
        fc = FileCache()
        fc.put("k", "v", expire=60)
        fc._connection().execute(
            "UPDATE entries SET value=? WHERE key=?",
            (pickle.dumps({"role": "admin"}), fc._id("k")),
        )
        fc._connection().commit()

        assert fc.get("k") is None

    def test_loads_rejects_non_bytes_blobs(self):
        with pytest.raises(ValueError):
            signing_module.loads("RNSC1-not-a-blob")
        with pytest.raises(ValueError):
            signing_module.loads(None)

    def test_entry_written_under_old_key_is_rejected_after_rotation(self, monkeypatch):
        # Written while "key-one" was configured...
        _patch_config(monkeypatch, key="key-one")
        monkeypatch.setattr(signing_module, "_key", None)
        writer = FileCache()
        writer.put("k", "v", expire=60)
        assert writer.get("k") == "v"

        # ...then the secret rotates (process restart simulated by reset).
        _patch_config(monkeypatch, key="key-two")
        monkeypatch.setattr(signing_module, "_key", None)
        reader = FileCache()

        assert reader.get("k") is None
        assert _db_row(reader, "k") is None

    def test_tampered_redis_entry_is_rejected_and_purged(self, redis_cache):
        redis_cache.put("k", {"a": 1}, expire=60)
        rid = redis_cache._id("k")
        entry = redis_cache._rd.data[rid]
        blob = bytearray(entry[0] if isinstance(entry, tuple) else entry)
        blob[7] ^= 0xFF  # signature region
        redis_cache._rd.data[rid] = bytes(blob)

        assert redis_cache.get("k") is None
        assert rid not in redis_cache._rd.data


class TestConfiguredSecretProtectsStorage:
    """The documented mitigation for C1: with a real ``key`` configured,
    blobs forged under the public default are refused (and purged) by both
    drivers."""

    def test_default_key_forgery_rejected_when_strong_secret_configured(
        self, monkeypatch
    ):
        blob = _forge_blob({"role": "admin"})  # signed with public "123"

        _patch_config(monkeypatch, key="a" * 64)
        monkeypatch.setattr(signing_module, "_key", None)

        fc = FileCache()
        fc.put("k", "v", expire=60)
        fc._connection().execute(
            "UPDATE entries SET value=? WHERE key=?", (blob, fc._id("k"))
        )
        fc._connection().commit()

        assert fc.get("k") is None
        assert _db_row(fc, "k") is None

    def test_default_key_forgery_rejected_on_redis_with_strong_secret(
        self, redis_cache, monkeypatch
    ):
        blob = _forge_blob({"role": "admin"})

        _patch_config(monkeypatch, key="a" * 64)
        monkeypatch.setattr(signing_module, "_key", None)
        redis_cache._key = None

        redis_cache.put("k", "v", expire=60)
        rid = redis_cache._id("k")
        redis_cache._rd.data[rid] = (blob, 60)

        assert redis_cache.get("k") is None
        assert rid not in redis_cache._rd.data

    def test_strong_secret_entries_do_not_verify_under_default_key(self, monkeypatch):
        # Operator signs entries under a strong configured secret...
        _patch_config(monkeypatch, key="a" * 64)
        monkeypatch.setattr(signing_module, "_key", None)
        strong = signing_module.dumps({"role": "admin"})

        # ...then a reader that lost the config falls back to the default.
        _patch_config(monkeypatch)
        monkeypatch.setattr(signing_module, "_key", None)

        with pytest.raises(ValueError):
            signing_module.loads(strong)
