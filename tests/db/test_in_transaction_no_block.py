from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Field,
    MongoDBAdapter,
    MySQLAdapter,
    ReModel,
    SQLiteAdapter,
)

from tests.db import _native_helpers as nh

ALL_BACKENDS = [SQLiteAdapter, MongoDBAdapter, MySQLAdapter]
BACKEND_NAMES = ["sqlite", "mongodb", "mysql"]

@pytest.mark.parametrize(
    "adapter_cls", ALL_BACKENDS, ids=BACKEND_NAMES
)
def test_no_transaction_reports_inactive(adapter_cls):
    adapter = adapter_cls()
    assert adapter._in_active_transaction() is False

@pytest.mark.parametrize(
    "adapter_cls", ALL_BACKENDS, ids=BACKEND_NAMES
)
def test_marker_set_reports_active(adapter_cls):
    adapter = adapter_cls()
    adapter._tx_session = object()
    try:
        assert adapter._in_active_transaction() is True
    finally:
        adapter._tx_session = None

@pytest.mark.parametrize(
    "adapter_cls", ALL_BACKENDS, ids=BACKEND_NAMES
)
def test_cleared_marker_returns_to_inactive(adapter_cls):
    adapter = adapter_cls()
    adapter._tx_session = object()
    assert adapter._in_active_transaction() is True
    adapter._tx_session = None
    assert adapter._in_active_transaction() is False

class Item(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    label: str

@pytest.mark.asyncio
async def test_lone_mutation_auto_commits_without_transaction():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Item])
    try:
        repo = db.repository(Item)

        assert adapter._in_active_transaction() is False
        created = await repo.create(Item(label="auto"))
        assert created.id is not None

        assert await repo.count() == 1
        assert await repo.exists(Item.label == "auto") is True

        rows = await nh.native_all(db, "items")
        assert [r["label"] for r in rows] == ["auto"]
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_batch_create_many_completes_without_transaction():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Item])
    try:
        repo = db.repository(Item)
        created = await repo.create_many(
            [Item(label=f"row-{i}") for i in range(3)]
        )
        assert len(created) == 3
        assert await repo.count() == 3
        assert adapter._in_active_transaction() is False
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_nested_transaction_not_supported():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Item])
    try:
        repo = db.repository(Item)

        async with db.transaction():
            assert adapter._in_active_transaction() is True
            await repo.create(Item(label="outer"))

            with pytest.raises(Exception):
                async with db.transaction():
                    await repo.create(Item(label="inner"))

            assert adapter._in_active_transaction() is True

        assert adapter._in_active_transaction() is False
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_nested_transaction_outer_survives_rejection():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Item])
    try:
        repo = db.repository(Item)

        async with db.transaction():
            await repo.create(Item(label="persist"))
            try:
                async with db.transaction():
                    await repo.create(Item(label="inner-fail"))
            except Exception:
                pass

            assert adapter._in_active_transaction() is True
            await repo.create(Item(label="after-fail"))

        assert adapter._in_active_transaction() is False
        rows = await nh.native_all(db, "items")
        assert sorted(r["label"] for r in rows) == ["after-fail", "persist"]
    finally:
        await db.disconnect()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_nontransactional_operation_not_blocked(kind):
    db = await nh.connect_schema(kind, [Item])
    try:
        adapter = db.adapter("primary")
        assert adapter._in_active_transaction() is False
        await db.repository(Item).create(Item(label="plain"))
        assert await nh.native_all(db, "items") != []
        assert adapter._in_active_transaction() is False
    finally:
        await nh.cleanup(db)
