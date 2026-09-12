import multiprocessing
import threading
import time
from unittest.mock import patch

import pytest

from renus.cache import Cache, FileCache, RedisCache, cache_func, get_backend

class _FakeRedis:

    def __init__(self):
        self.data = {}

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

@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    from renus.cache import file as file_module

    db_path = tmp_path / "cache.sqlite"

    def fake_get(self, name, *default):
        if name == "cache_file_path":
            return str(db_path)
        return default[0] if default else None

    original_conn = file_module._conn
    file_module._conn = None
    Cache.clear_instances()
    try:
        with patch.object(file_module.Config, "get", fake_get):
            yield db_path
    finally:
        file_module._conn = original_conn
        Cache.clear_instances()

@pytest.fixture
def file_cache(isolated_db):
    return FileCache()

@pytest.fixture
def redis_cache(isolated_db):
    fake = _FakeRedis()
    with (
        patch("renus.cache.redis._redis_lib", new=object()),
        patch("renus.cache.redis._get_client", return_value=fake),
    ):
        yield RedisCache()

def _parallel_file_increment_worker(db_key, amount, count):
    import renus.cache.file as file_module

    Cache.clear_instances()
    file_module._conn = None
    cache = Cache()
    for _ in range(count):
        cache.increment(db_key, amount, expire=60)

def _parallel_redis_increment(cache, key, amount, count):
    for _ in range(count):
        cache.increment(key, amount, expire=60)

class TestFileCache:
    def test_put_and_get_round_trip(self, file_cache):
        file_cache.put("k", {"a": 1, "b": [1, 2]}, expire=60)
        assert file_cache.get("k") == {"a": 1, "b": [1, 2]}

    def test_get_missing_returns_default(self, file_cache):
        assert file_cache.get("missing", "fallback") == "fallback"
        assert file_cache.get("missing") is None

    def test_expired_value_returns_default_and_is_purged(self, file_cache):
        file_cache.put("k", "v", expire=1)
        assert file_cache.get("k") == "v"
        time.sleep(1.2)
        assert file_cache.get("k") is None
        assert file_cache.expire("k") == -1

    def test_never_expire_entries_stay(self, file_cache):
        file_cache.put("k", "keep", expire=-1)
        assert file_cache.get("k") == "keep"
        assert file_cache.expire("k") == -1

    def test_ttl_is_positive_and_bounded(self, file_cache):
        file_cache.put("k", "v", expire=10)
        ttl = file_cache.expire("k")
        assert 0 < ttl <= 10

    def test_increment_seeds_when_absent_and_adds_value(self, file_cache):
        assert file_cache.increment("cnt", 5, expire=60) == 5
        assert file_cache.increment("cnt", 5, expire=60) == 10
        assert file_cache.increment("cnt", 5, expire=60) == 15
        assert file_cache.get("cnt") == 15

    def test_delete_removes_entry(self, file_cache):
        file_cache.put("k", "v", expire=60)
        assert file_cache.delete("k") is True
        assert file_cache.get("k") is None

    def test_delete_missing_returns_false(self, file_cache):
        assert file_cache.delete("nope") is False

    def test_delete_expired_only_removes_stale(self, file_cache):
        file_cache.put("gone", 1, expire=-1)
        file_cache.put("stale", 2, expire=1)
        time.sleep(1.2)
        removed = file_cache.delete_expired()
        assert removed >= 1
        assert file_cache.get("stale") is None
        assert file_cache.get("gone") == 1

    def test_prefix_isolates_keys(self, isolated_db):
        c1 = Cache(prefix="users:")
        c2 = Cache(prefix="tokens:")
        c1.put("x", 1, expire=60)
        assert c1.get("x") == 1
        assert c2.get("x") is None

class TestRedisCache:
    def test_put_and_get_round_trip(self, redis_cache):
        redis_cache.put("k", {"a": 1}, expire=60)
        assert redis_cache.get("k") == {"a": 1}

    def test_get_missing_returns_default(self, redis_cache):
        assert redis_cache.get("missing", "d") == "d"
        assert redis_cache.get("missing") is None

    def test_ttl_and_never_expire(self, redis_cache):
        redis_cache.put("ttl", "v", expire=10)
        assert redis_cache.expire("ttl") == 10
        redis_cache.put("forever", "v", expire=-1)
        assert redis_cache.expire("forever") == -1

    def test_increment_seeds_when_absent_and_adds_value(self, redis_cache):
        assert redis_cache.increment("cnt", 5, expire=60) == 5
        assert redis_cache.increment("cnt", 5, expire=60) == 10

    def test_delete(self, redis_cache):
        redis_cache.put("k", "v", expire=60)
        assert redis_cache.delete("k") == 1
        assert redis_cache.get("k") is None

    def test_delete_missing_returns_zero(self, redis_cache):
        assert redis_cache.delete("nope") == 0

    def test_requires_redis_package(self):
        with patch("renus.cache.redis._redis_lib", None):
            with pytest.raises(RuntimeError):
                RedisCache()

class TestCacheFacade:
    def test_default_driver_is_file(self, isolated_db):
        cache = Cache()
        assert cache.driver == "file"
        assert isinstance(cache.backend, FileCache)

    def test_redis_driver_selects_redis_backend(self):
        with (
            patch("renus.cache.redis._redis_lib", new=object()),
            patch("renus.cache.redis._get_client", return_value=_FakeRedis()),
        ):
            cache = Cache(driver="redis")
            assert isinstance(cache.backend, RedisCache)

    def test_unknown_driver_raises(self):
        with pytest.raises(ValueError, match="Unknown cache driver"):
            Cache(driver="mongo")

    def test_get_backend_returns_file(self):
        assert isinstance(get_backend("file", "p:"), FileCache)

    def test_backends_are_reused_per_config(self):
        a = Cache(prefix="p")
        b = Cache(prefix="p")
        c = Cache(prefix="q")
        assert a.backend is b.backend
        assert a.backend is not c.backend

    @pytest.mark.asyncio
    async def test_async_put_get(self):
        cache = Cache()
        await cache.aput("k", 42, expire=10)
        assert await cache.aget("k") == 42

    @pytest.mark.asyncio
    async def test_async_increment_and_expire(self):
        cache = Cache()
        await cache.aput("k", 1, expire=10)
        assert await cache.aget("k") == 1
        assert await cache.aincrement("k", 5, expire=10) == 6
        assert await cache.aincrement("fresh", 5, expire=10) == 5
        assert 0 < await cache.aexpire("k") <= 10
        assert await cache.adelete("k") is True

class TestCacheFunc:
    def test_caches_result_across_calls(self):
        calls = []

        @cache_func(60)
        def add(a, b):
            calls.append((a, b))
            return a + b

        assert add(1, 2) == 3
        assert add(1, 2) == 3
        assert len(calls) == 1

    def test_distinct_args_are_not_cached_together(self):
        calls = []

        @cache_func(60)
        def double(x):
            calls.append(x)
            return x * 2

        assert double(1) == 2
        assert double(2) == 4
        assert len(calls) == 2

class TestConcurrency:
    def test_file_increment_atomic_across_threads(self, file_cache):
        n_threads, per = 8, 100
        threads = [
            threading.Thread(target=_parallel_redis_increment, args=(file_cache, "k", 1, per))
            for _ in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert file_cache.get("k") == n_threads * per

    def test_redis_increment_atomic_across_threads(self, redis_cache):
        n_threads, per = 8, 100
        threads = [
            threading.Thread(target=_parallel_redis_increment, args=(redis_cache, "k", 2, per))
            for _ in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert redis_cache.get("k") == n_threads * per * 2

    def test_file_increment_atomic_across_processes(self, isolated_db):
        n_proc, per, amount = 4, 50, 1
        cache = Cache()
        cache.delete("k")

        ctx = multiprocessing.get_context("fork")
        procs = [
            ctx.Process(
                target=_parallel_file_increment_worker, args=("k", amount, per)
            )
            for _ in range(n_proc)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()

        assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]

        assert cache.get("k") == n_proc * per * amount
