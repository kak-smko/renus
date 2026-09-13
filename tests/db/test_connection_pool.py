from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from renus.db import (
    Database,
    DatabaseError,
    DatabaseField,
    DuplicateKeyError,
    Field,
    IntegrityError,
    MongoDBAdapter,
    MySQLAdapter,
    ReModel,
    SQLiteAdapter,
)
from renus.db import errors
from renus.db.core.exceptions import ConnectionError as DBConnectionError
from renus.db.mysql.adapter import (
    DEFAULT_MYSQL_CONNECT_TIMEOUT,
    DEFAULT_MYSQL_MAX_POOL,
    DEFAULT_MYSQL_MIN_POOL,
)

from tests.db import _native_helpers as nh

class Item(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    code: str = Field(database=DatabaseField(unique=True))
    value: float = 0.0

@pytest.mark.asyncio
async def test_database_context_manager_sqlite_closes_on_exit():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    assert db.adapter("primary")._conn is None
    async with Database(SQLiteAdapter({"database": ":memory:"})) as db:
        await db.create_schema([Item])
        await db.repository(Item).create(Item(code="c1"))
        assert db.adapter("primary")._conn is not None
    assert db.adapter("primary")._conn is None

@pytest.mark.asyncio
async def test_database_context_manager_mysql_connects_and_closes():
    adapter = MySQLAdapter({"host": "127.0.0.1", "database": "test_db"})
    connect = AsyncMock()
    disconnect = AsyncMock()
    adapter.connect = connect
    adapter.disconnect = disconnect

    db = Database(adapter)
    async with db as entered:
        assert entered is db
    connect.assert_awaited_once()
    disconnect.assert_awaited_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [pytest.param("mongodb", marks=pytest.mark.skipif(
    not nh.mongo_ready(), reason="MongoDB not reachable"))])
async def test_database_context_manager_mongodb_connects_and_closes(kind):
    db = Database(MongoDBAdapter({"uri": nh.MONGO_URI, "database": nh._unique_db()}))
    try:
        async with db:
            assert await db.health_check() is True

        assert db.adapter("primary")._client is None
    finally:
        await db.disconnect()

def test_mysql_pool_config_maps_to_connect_params():
    cfg = {
        "host": "db.internal",
        "port": 3307,
        "username": "app", "password": "pw",
        "database": "appdb",
        "max_pool": 40, "min_pool": 6, "connect_timeout": 12,
    }
    adapter = MySQLAdapter(cfg)

    assert int(cfg.get("max_pool", DEFAULT_MYSQL_MAX_POOL)) == 40
    assert int(cfg.get("min_pool", DEFAULT_MYSQL_MIN_POOL)) == 6
    assert int(cfg.get("connect_timeout", DEFAULT_MYSQL_CONNECT_TIMEOUT)) == 12

@pytest.mark.asyncio
async def test_mysql_reconnect_after_connection_drop():
    adapter = MySQLAdapter()
    calls = {"n": 0}

    async def flaky_acquire():
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("mysql gone away: connection lost")
        return mock_conn()

    def mock_conn():
        conn = MagicMock()
        conn.cursor = MagicMock(return_value=MagicMock(
            __aenter__=AsyncMock(return_value=AsyncMock(
                execute=AsyncMock(),
                fetchall=AsyncMock(return_value=[{"id": 1, "code": "c1"}]),
            )),
            __aexit__=AsyncMock(return_value=None),
        ))
        return conn

    adapter._pool = MagicMock()
    adapter._pool.acquire = flaky_acquire
    adapter._pool.release = MagicMock()

    adapter.connect = AsyncMock(side_effect=lambda: setattr(
        adapter, "_pool", MagicMock(acquire=flaky_acquire, release=MagicMock())
    ))
    adapter.disconnect = AsyncMock()

    repo = __import__("renus.db", fromlist=["Repository"]).Repository(adapter, Item)
    rows = await adapter.execute_query(repo.query().ast)
    assert rows == [{"id": 1, "code": "c1"}]
    assert calls["n"] == 2
    adapter.disconnect.assert_awaited()
    adapter.connect.assert_awaited_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [pytest.param("mongodb", marks=pytest.mark.skipif(
    not nh.mongo_ready(), reason="MongoDB not reachable"))])
async def test_mongodb_reconnect_after_connection_drop(kind):
    db = Database(MongoDBAdapter({"uri": nh.MONGO_URI, "database": nh._unique_db()}))
    await db.connect()
    try:
        assert await db.health_check() is True

        await db.adapter("primary").disconnect()
        assert await db.health_check() is False

        await db.adapter("primary").connect()
        assert await db.health_check() is True
    finally:
        await db.disconnect()

@pytest.mark.parametrize(
    "label,backend,driver_exc,expected",
    [
        ("MySQL", "mysql", Exception("1062 Duplicate entry 'x' for key 'code'"), DuplicateKeyError),
        ("MySQL", "mysql", Exception("foreign key constraint fails"), IntegrityError),
        ("MySQL", "mysql", Exception("mysql gone away: connection lost"), DBConnectionError),
        ("MySQL", "mysql", Exception("Table 'db.x' doesn't exist"), DatabaseError),
        ("MongoDB", "mongodb", Exception("E11000 duplicate key error"), DuplicateKeyError),
        ("MongoDB", "mongodb", Exception("connection lost to server"), DBConnectionError),
        ("MongoDB", "mongodb", Exception("some pipeline error"), DatabaseError),
    ],
)
def test_translate_driver_error_table(label, backend, driver_exc, expected):
    result = errors.translate_driver_error(label, backend, driver_exc, "mutation")
    assert isinstance(result, expected)

    assert result.__class__ is expected
