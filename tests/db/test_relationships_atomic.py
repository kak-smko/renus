from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseField,
    DuplicateKeyError,
    Field,
    IntegrityError,
    Model,
    OneToMany,
    SQLiteAdapter,
)
from tests.db._conformance import cleanup, conformance_tests, database_for


class Addr(Model):
    city: str


class Tag(Model):
    label: str


class Item(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: Addr | None = None
    tags: list[Tag] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)


class AtomicChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    item_id: str = ""


class AtomicItem(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    children: list[AtomicChild] = OneToMany(
        AtomicChild, foreign_key="item_id", on_save="cascade"
    )


class AtomicKeyChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    owner_code: str | None = None


class AtomicKeyOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    code: str | None = Field(
        default=None,
        database=DatabaseField(unique=True),
    )
    children: list[AtomicKeyChild] = OneToMany(
        AtomicKeyChild,
        local_key="code",
        foreign_key="owner_code",
        on_save="cascade",
        on_update="cascade",
    )


ADAPTERS = conformance_tests()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_fields_roundtrip_update_and_query(kind: str):
    db = await database_for(kind, [Item])
    try:
        repo = db.repository(Item)
        item = await repo.create(
            Item(
                id="item-1",
                name="book",
                address={"city": "Oslo"},
                tags=[{"label": "python"}, Tag(label="database")],
                attributes={"color": "blue"},
            )
        )

        assert isinstance(item.address, Addr)
        assert all(isinstance(tag, Tag) for tag in item.tags)

        loaded = await repo.where(Item.id == "item-1").first()
        assert loaded is not None
        assert loaded.address == Addr(city="Oslo")
        assert [tag.label for tag in loaded.tags] == ["python", "database"]
        assert loaded.attributes == {"color": "blue"}

        matching_address = await repo.where(Item.address.city == "Oslo").first()
        assert matching_address is not None
        assert matching_address.id == "item-1"
        matching_tag = await repo.where(Item.tags.any(Tag.label == "python")).first()
        assert matching_tag is not None
        assert matching_tag.id == "item-1"

        loaded.address = Addr(city="Helsinki")
        loaded.tags = [Tag(label="renus")]
        loaded.attributes = {"color": "green"}
        await repo.save(loaded)

        updated = await repo.where(Item.id == "item-1").first()
        assert updated is not None
        assert updated.address == Addr(city="Helsinki")
        assert [tag.label for tag in updated.tags] == ["renus"]
        assert updated.attributes == {"color": "green"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
async def test_cascading_relationship_writes_are_atomic():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([AtomicItem, AtomicChild])
    try:
        repo = db.repository(AtomicItem)
        with pytest.raises(IntegrityError):
            await repo.create(
                AtomicItem(
                    id="item-1",
                    children=[AtomicChild(id="child-1"), AtomicChild(id="child-1")],
                )
            )

        assert await repo.count() == 0
        assert await db.repository(AtomicChild).count() == 0
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_local_key_update_cascade_rolls_back_with_parent_update():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([AtomicKeyOwner, AtomicKeyChild])
    try:
        owners = db.repository(AtomicKeyOwner)
        children = db.repository(AtomicKeyChild)
        await owners.create(
            AtomicKeyOwner(
                id="owner-1",
                code="code-1",
                children=[AtomicKeyChild(id="child-1")],
            )
        )
        await owners.create(AtomicKeyOwner(id="owner-2", code="code-2"))
        await owners.create(
            AtomicKeyOwner(
                id="owner-null",
                children=[AtomicKeyChild(id="child-null")],
            )
        )
        null_child = await children.where(AtomicKeyChild.id == "child-null").first()
        assert null_child.owner_code is None

        owner = await owners.where(AtomicKeyOwner.id == "owner-1").first()
        owner.code = "code-2"
        with pytest.raises(DuplicateKeyError):
            await owners.save(owner)

        stored_owner = await owners.where(AtomicKeyOwner.id == "owner-1").first()
        stored_child = await children.where(AtomicKeyChild.id == "child-1").first()
        assert stored_owner.code == "code-1"
        assert stored_child.owner_code == "code-1"
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_cascading_relationship_writes_are_atomic2():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([AtomicItem, AtomicChild])
    try:
        repo = db.repository(AtomicItem)
        await repo.create(
                AtomicItem(
                    id="item-1",
                    children=[AtomicChild(id="child-1"), AtomicChild(id="child-2")],
                )
            )

        assert await repo.count() == 1
        assert await db.repository(AtomicChild).count() == 2
    finally:
        await db.disconnect()