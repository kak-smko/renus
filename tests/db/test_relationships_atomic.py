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
    OneToOne,
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


class KeyUpdateChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    label: str


class KeyUpdateParent(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    child: KeyUpdateChild = OneToOne(
        KeyUpdateChild,
        foreign_key="id",
        on_save="cascade",
        on_update="cascade",
    )


class NullingChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    owner_code: str | None = None


class NullingParent(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    code: str = Field(database=DatabaseField(unique=True))
    child: NullingChild = OneToOne(
        NullingChild,
        local_key="code",
        foreign_key="owner_code",
        on_save="cascade",
        on_update="set null",
    )


class DefaultingChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    owner_code: str = Field(default="orphan")


class DefaultingParent(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    code: str = Field(database=DatabaseField(unique=True))
    child: DefaultingChild = OneToOne(
        DefaultingChild,
        local_key="code",
        foreign_key="owner_code",
        on_save="cascade",
        on_update="set default",
    )


class DeleteChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    owner_code: str | None = None


class DeleteParent(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    code: str = Field(database=DatabaseField(unique=True))
    children: list[DeleteChild] = OneToMany(
        DeleteChild,
        local_key="code",
        foreign_key="owner_code",
        on_save="cascade",
        on_delete="cascade",
    )


class BulkDeleteCodeChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    owner_code: str | None = None


class BulkDeleteSlugChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    owner_slug: str | None = None


class BulkDeleteOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    code: str
    slug: str
    children_by_code: list[BulkDeleteCodeChild] = OneToMany(
        BulkDeleteCodeChild,
        local_key="code",
        foreign_key="owner_code",
        on_delete="cascade",
    )
    children_by_slug: list[BulkDeleteSlugChild] = OneToMany(
        BulkDeleteSlugChild,
        local_key="slug",
        foreign_key="owner_slug",
        on_delete="cascade",
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
async def test_parent_key_update_preserves_included_child_edits():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([KeyUpdateParent, KeyUpdateChild])
    try:
        parents = db.repository(KeyUpdateParent)
        children = db.repository(KeyUpdateChild)
        await parents.create(
            KeyUpdateParent(
                id="old-key",
                child=KeyUpdateChild(id="old-key", label="before"),
            )
        )

        parent = await parents.where(KeyUpdateParent.id == "old-key").include(
            KeyUpdateParent.child
        ).first()
        parent.id = "new-key"
        parent.child.label = "after"
        await parents.save(parent)

        stored = await children.where(KeyUpdateChild.id == "new-key").first()
        assert stored is not None
        assert stored.label == "after"
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_set_null_update_is_not_overwritten_by_save_cascade():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([NullingParent, NullingChild])
    try:
        parents = db.repository(NullingParent)
        children = db.repository(NullingChild)
        await parents.create(
            NullingParent(
                id="parent-1",
                code="before",
                child=NullingChild(id="child-1", owner_code="before"),
            )
        )

        parent = await parents.where(NullingParent.id == "parent-1").include(
            NullingParent.child
        ).first()
        parent.code = "after"
        await parents.save(parent)

        stored = await children.where(NullingChild.id == "child-1").first()
        assert stored is not None
        assert stored.owner_code is None
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_set_default_update_is_not_overwritten_by_save_cascade():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([DefaultingParent, DefaultingChild])
    try:
        parents = db.repository(DefaultingParent)
        children = db.repository(DefaultingChild)
        await parents.create(
            DefaultingParent(
                id="parent-1",
                code="before",
                child=DefaultingChild(id="child-1", owner_code="before"),
            )
        )

        parent = await parents.where(DefaultingParent.id == "parent-1").include(
            DefaultingParent.child
        ).first()
        parent.code = "after"
        await parents.save(parent)

        stored = await children.where(DefaultingChild.id == "child-1").first()
        assert stored is not None
        assert stored.owner_code == "orphan"
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_delete_uses_persisted_parent_and_local_keys():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([DeleteParent, DeleteChild])
    try:
        parents = db.repository(DeleteParent)
        children = db.repository(DeleteChild)
        await parents.create(
            DeleteParent(
                id="old-id",
                code="old-code",
                children=[DeleteChild(id="child-1", owner_code="old-code")],
            )
        )

        parent = await parents.where(DeleteParent.id == "old-id").first()
        parent.id = "unsaved-id"
        parent.code = "unsaved-code"
        assert await parents.delete(parent) == 1

        assert await parents.where(DeleteParent.id == "old-id").count() == 0
        assert await children.count() == 0
    finally:
        await db.disconnect()


@pytest.mark.asyncio
async def test_bulk_delete_projects_all_relationship_keys_in_one_parent_query():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([BulkDeleteOwner, BulkDeleteCodeChild, BulkDeleteSlugChild])
    try:
        owners = db.repository(BulkDeleteOwner)
        code_children = db.repository(BulkDeleteCodeChild)
        slug_children = db.repository(BulkDeleteSlugChild)
        await owners.create(
            BulkDeleteOwner(id="owner-1", code="code-1", slug="slug-1")
        )
        await code_children.create(
            BulkDeleteCodeChild(id="code-child-1", owner_code="code-1")
        )
        await slug_children.create(
            BulkDeleteSlugChild(id="slug-child-1", owner_slug="slug-1")
        )

        adapter = db.adapter()
        original_execute_query = adapter.execute_query
        parent_queries = 0

        async def count_parent_queries(compiled):
            nonlocal parent_queries
            if getattr(compiled, "source", None) is BulkDeleteOwner:
                parent_queries += 1
            return await original_execute_query(compiled)

        adapter.execute_query = count_parent_queries
        assert await owners.delete_many(BulkDeleteOwner.id == "owner-1") == 1
        assert parent_queries == 1
        assert await code_children.count() == 0
        assert await slug_children.count() == 0
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