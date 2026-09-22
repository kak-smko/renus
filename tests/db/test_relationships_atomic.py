from __future__ import annotations

import pytest

from renus.db import (
    DatabaseField,
    Embedded,
    EmbeddedMany,
    Field,
    Include,
    Model,
)
from renus.db.mutation.ast import Insert, InsertMany
from tests.db._conformance import cleanup, conformance_tests, database_for


class Addr(Model):
    city: str


class Tag(Model):
    label: str


class Item(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str = ""
    address: Addr = Embedded(Addr)
    tags: list[Tag] = EmbeddedMany(Tag)


class RawEmbeddedChild(Model):
    name: str
    attributes: dict
    values: list


class RawEmbeddedOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    children: list[RawEmbeddedChild] = EmbeddedMany(RawEmbeddedChild)


ADAPTERS = conformance_tests()


async def _make_item_database(kind: str):
    db = await database_for(kind, [Item])
    return db, db.repository(Item)


async def _seed_item(repo) -> None:
    await repo.create(
        Item(id="item-1", name="w", address=Addr(city="old"), tags=[Tag(label="a")])
    )

    loaded = await repo.query().include(Item.address, Item.tags).first()
    assert loaded is not None
    assert loaded.address.city == "old"
    assert [tag.label for tag in loaded.tags] == ["a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_raw_embedded_relationship_uses_prefixed_table(kind: str):
    db = await database_for(kind, [RawEmbeddedOwner])
    try:
        repo = db.repository(RawEmbeddedOwner)
        await repo.create(
            RawEmbeddedOwner(
                id="owner-1",
                children=[
                    RawEmbeddedChild(
                        name="child-1",
                        attributes={"label": "one"},
                        values=["first"],
                    )
                ],
            )
        )

        loaded = await repo.query().include(RawEmbeddedOwner.children).first()
        assert loaded is not None
        assert len(loaded.children) == 1
        assert loaded.children[0].name == "child-1"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_embedded_one_persist_rolls_back_delete_on_failed_insert(kind: str):
    db, repo = await _make_item_database(kind)
    try:
        await _seed_item(repo)
        adapter = db.adapter("primary")
        if adapter.nested_documents:
            pytest.skip("document adapters persist embedded values in the parent mutation")

        original = adapter.execute_mutation

        async def failing_insert(compiled):
            if isinstance(compiled, Insert):
                raise RuntimeError("insert failure")
            return await original(compiled)

        adapter.execute_mutation = failing_insert
        item = (await repo.query().include(Item.address).first())
        assert item is not None
        item.address = Addr(city="new")
        item._mark_dirty()

        with pytest.raises(RuntimeError, match="insert failure"):
            await repo.save(item)

        adapter.execute_mutation = original

        loaded = await repo.query().include(Item.address).first()
        assert loaded is not None
        assert loaded.address.city == "old"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_embedded_many_persist_rolls_back_delete_on_failed_insert(kind: str):
    db, repo = await _make_item_database(kind)
    try:
        await _seed_item(repo)
        adapter = db.adapter("primary")
        if adapter.nested_documents:
            pytest.skip("document adapters persist embedded values in the parent mutation")

        original = adapter.execute_mutation

        async def failing_insert_many(compiled):
            if isinstance(compiled, InsertMany):
                raise RuntimeError("bulk insert failure")
            return await original(compiled)

        adapter.execute_mutation = failing_insert_many
        item = (await repo.query().include(Item.tags).first())
        assert item is not None
        item.tags = [Tag(label="x"), Tag(label="y")]
        item._mark_dirty()

        with pytest.raises(RuntimeError, match="bulk insert failure"):
            await repo.save(item)

        adapter.execute_mutation = original

        loaded = await repo.query().include(Item.tags).first()
        assert loaded is not None
        assert [tag.label for tag in loaded.tags] == ["a"]
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_embedded_persist_saves_atomically_when_insert_succeeds(kind: str):
    db, repo = await _make_item_database(kind)
    try:
        await _seed_item(repo)

        item = await repo.query().include(Item.address, Item.tags).first()
        assert item is not None
        item.address = Addr(city="new")
        item.tags = [Tag(label="x")]
        item._mark_dirty()
        await repo.save(item)

        loaded = await repo.query().include(Item.address, Item.tags).first()
        assert loaded is not None
        assert loaded.address.city == "new"
        assert [tag.label for tag in loaded.tags] == ["x"]
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_rolls_back_parent_insert_on_failed_embedded_write(kind: str):
    db, repo = await _make_item_database(kind)
    try:
        adapter = db.adapter("primary")
        if adapter.nested_documents:
            pytest.skip("document adapters persist embedded values in the parent mutation")

        original = adapter.execute_mutation

        async def failing_embedded_insert_many(compiled):
            if isinstance(compiled, InsertMany):
                raise RuntimeError("embedded insert failure")
            return await original(compiled)

        adapter.execute_mutation = failing_embedded_insert_many

        with pytest.raises(RuntimeError, match="embedded insert failure"):
            await repo.create(
                Item(
                    id="item-1",
                    name="w",
                    address=Addr(city="new"),
                    tags=[Tag(label="x")],
                )
            )

        adapter.execute_mutation = original
        assert await repo.count() == 0
    finally:
        await cleanup(db)
