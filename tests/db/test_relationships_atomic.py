from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Embedded,
    EmbeddedMany,
    Field,
    Model,
    SQLiteAdapter,
)
from renus.db.mutation.ast import Insert, InsertMany

class Addr(Model):
    city: str

class Tag(Model):
    label: str

class Item(Model):
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

def _sql_rows(adapter, sql: str) -> list[dict]:
    return [dict(r) for r in adapter._sqlite_db.execute(sql).fetchall()]

async def _seed_item(repo, adapter) -> None:
    await repo.create(
        Item(id="1", name="w", address=Addr(city="old"), tags=[Tag(label="a")])
    )
    assert _sql_rows(adapter, "SELECT city FROM items_address") == [{"city": "old"}]
    assert [r["label"] for r in _sql_rows(adapter, "SELECT label FROM items_tags")] == [
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

        assert _sql_rows(adapter, "SELECT city FROM items_address") == [
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

        assert [r["label"] for r in _sql_rows(adapter, "SELECT label FROM items_tags")] == [
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

        assert _sql_rows(adapter, "SELECT city FROM items_address") == [
            {"city": "new"}
        ]
        assert [r["label"] for r in _sql_rows(adapter, "SELECT label FROM items_tags")] == [
            "x"
        ]
    finally:
        await db.disconnect()


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

        assert _sql_rows(adapter, "SELECT id FROM items") == []
    finally:
        await db.disconnect()
