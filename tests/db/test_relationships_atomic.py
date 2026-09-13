from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Embedded,
    EmbeddedMany,
    Field,
    ReModel,
    SQLiteAdapter,
)
from renus.db.core.capabilities import DatabaseCapabilities
from renus.db.mutation.ast import Insert, InsertMany

class Addr(ReModel):
    city: str

class Tag(ReModel):
    label: str

class Item(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str = ""
    address: Addr = Embedded(Addr)
    tags: list[Tag] = EmbeddedMany(Tag)

async def _make_item_adapter() -> tuple[Database, object, object]:
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([Item])
    repo = db.repository(Item)
    return db, db.adapter("primary"), repo

async def _seed_item(repo, adapter) -> None:
    await repo.create(
        Item(id="1", name="w", address=Addr(city="old"), tags=[Tag(label="a")])
    )
    assert await adapter.execute_raw("SELECT city FROM items_address") == [{"city": "old"}]
    assert [r["label"] for r in await adapter.execute_raw("SELECT label FROM items_tags")] == [
        "a"
    ]

@pytest.mark.asyncio
async def test_embedded_one_persist_rolls_back_delete_on_failed_insert():
    db, adapter, repo = await _make_item_adapter()
    try:
        await _seed_item(repo, adapter)

        original = adapter.execute_mutation

        async def failing_insert(compiled):

            if isinstance(compiled, Insert):
                raise RuntimeError("insert failure")
            return await original(compiled)

        adapter.execute_mutation = failing_insert
        item = (await repo.query().all())[0]
        item.address = Addr(city="new")
        item._mark_dirty()

        with pytest.raises(RuntimeError, match="insert failure"):
            await repo.save(item)

        adapter.execute_mutation = original

        assert await adapter.execute_raw("SELECT city FROM items_address") == [
            {"city": "old"}
        ]
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_embedded_many_persist_rolls_back_delete_on_failed_insert():
    db, adapter, repo = await _make_item_adapter()
    try:
        await _seed_item(repo, adapter)

        original = adapter.execute_mutation

        async def failing_insert_many(compiled):

            if isinstance(compiled, InsertMany):
                raise RuntimeError("bulk insert failure")
            return await original(compiled)

        adapter.execute_mutation = failing_insert_many
        item = (await repo.query().all())[0]
        item.tags = [Tag(label="x"), Tag(label="y")]
        item._mark_dirty()

        with pytest.raises(RuntimeError, match="bulk insert failure"):
            await repo.save(item)

        adapter.execute_mutation = original

        assert [r["label"] for r in await adapter.execute_raw("SELECT label FROM items_tags")] == [
            "a"
        ]
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_embedded_persist_saves_atomically_when_insert_succeeds():
    db, adapter, repo = await _make_item_adapter()
    try:
        await _seed_item(repo, adapter)

        item = (await repo.query().all())[0]
        item.address = Addr(city="new")
        item.tags = [Tag(label="x")]
        item._mark_dirty()
        await repo.save(item)

        assert await adapter.execute_raw("SELECT city FROM items_address") == [
            {"city": "new"}
        ]
        assert [r["label"] for r in await adapter.execute_raw("SELECT label FROM items_tags")] == [
            "x"
        ]
    finally:
        await db.disconnect()

class _NoBulk(SQLiteAdapter):

    capabilities: DatabaseCapabilities = DatabaseCapabilities(
        transactions=True,
        nested_documents=False,
        joins=True,
        foreign_keys=True,
        upsert=True,
        returning=True,
        json=True,
        arrays=False,
        cursor_pagination=True,
        bulk_operations=False,
        indexes=True,
        constraints=True,
    )

@pytest.mark.asyncio
async def test_create_rolls_back_parent_insert_on_failed_embedded_write():
    db, adapter, repo = await _make_item_adapter()
    try:
        original = adapter.execute_mutation

        async def failing_embedded_insert_many(compiled):

            if isinstance(compiled, InsertMany):
                raise RuntimeError("embedded insert failure")
            return await original(compiled)

        adapter.execute_mutation = failing_embedded_insert_many

        with pytest.raises(RuntimeError, match="embedded insert failure"):
            await repo.create(
                Item(id="1", name="w", address=Addr(city="new"), tags=[Tag(label="x")])
            )

        adapter.execute_mutation = original

        assert await adapter.execute_raw("SELECT id FROM items") == []
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_create_many_fallback_rolls_back_earlier_writes_on_mid_batch_failure():
    db = Database(_NoBulk({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([Item])
    try:
        adapter = db.adapter("primary")
        repo = db.repository(Item)

        await adapter.execute_raw('INSERT INTO items (id, name) VALUES (?, ?)', ("dup", "existing"))
        assert [r["id"] for r in await adapter.execute_raw("SELECT id FROM items")] == ["dup"]

        from renus.db.core.exceptions import DuplicateKeyError

        with pytest.raises(DuplicateKeyError):
            await repo.create_many([Item(id="new"), Item(id="dup")])

        assert [r["id"] for r in await adapter.execute_raw("SELECT id FROM items")] == ["dup"]
    finally:
        await db.disconnect()
