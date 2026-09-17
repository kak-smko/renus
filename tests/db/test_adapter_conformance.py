"""Conformance suite: the standard operations every adapter must support.

Each test here runs against every registered adapter driver (see
``tests/db/_conformance.py``). A new backend joins the suite by registering an
``AdapterDriver``; if it passes this whole module it is correctly implemented
for the standard Renus database operations.

Run with::

    venv/bin/python -m pytest tests/db/test_adapter_conformance.py
"""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from renus.config import Config
from renus.db import (
    ID,
    Avg,
    Column,
    Count,
    Database,
    DatabaseField,
    DuplicateKeyError,
    Embedded,
    EmbeddedMany,
    Field,
    Include,
    IntegrityError,
    LoadingStrategy,
    ManyToMany,
    ManyToOne,
    Max,
    MigrationChecksumError,
    MigrationManager,
    Min,
    OneToMany,
    OneToOne,
    ReferentialAction,
    RelationshipKind,
    Model,
    SaveAction,
    Sum,
)
from renus.db.models.id import ID
from renus.db.query.ast import Path, QueryAST
from tests.db.deep_relation_models import DEEP_RELATION_FAMILIES
from tests.db.deep_embedded_models import (
    DeepEmbedded1,
    DeepEmbedded2,
    DeepEmbedded3,
    DeepEmbedded4,
    DeepEmbedded5,
    DeepEmbedded6,
    DeepEmbedded7,
    DeepMany1,
    DeepMany2,
    DeepMany3,
    DeepMany4,
    DeepMany5,
    DeepMany6,
    DeepManyLeaf,
    DeepRoot,
)
from tests.db._conformance import (
    Citizen,
    Contact,
    Dept,
    Version,
    Employee,
    Item,
    Passport,
    Post,
    Profile,
    Role,
    SoftUser,
    Tag,
    User,
    cleanup,
    conformance_tests,
    database_for,
)

ADAPTERS = conformance_tests()


def _u(uid: str, username: str, **kw):
    defaults = {"name": None, "age": 0, "active": True}
    defaults.update(kw)
    return User(id=uid, username=username, **defaults)


def _p(pid: str, title: str, user_id: str = ""):
    return Post(id=pid, title=title, user_id=user_id)


_row_count_models: dict[str, type] = {}


def _row_count_model(table: str) -> type:
    """Return a lightweight model bound to an existing table/collection."""
    model = _row_count_models.get(table)
    if model is None:
        meta = type("Meta", (), {"table": table})
        model = type(f"_RowCount_{table}", (Model,), {"Meta": meta})
        _row_count_models[table] = model
    return model


async def _row_counts(db, *tables: str) -> dict[str, int]:
    """Return the number of rows stored in each table/collection."""
    return {t: await db.repository(_row_count_model(t)).count() for t in tables}


async def _table_names(db) -> set[str]:
    """Return lower-cased table/collection names on the database."""
    return {t.lower() for t in await db.tables()}


_known_mig_models: dict[tuple[str, tuple[str, ...]], type] = {}


def _mig_model(table: str, fields: dict[str, type]) -> type:
    """Build a Model bound to a migration-created table.

    The model has a string ``id`` primary key plus the requested fields, and
    is cached so repeated builds with the same shape share one class.
    """
    key = (table, tuple(sorted(fields)))
    cached = _known_mig_models.get(key)
    if cached is not None:
        return cached
    annotations: dict[str, type] = {"id": str}
    attrs: dict[str, Any] = {"id": Field(database=DatabaseField(primary_key=True))}
    for name, typ in fields.items():
        annotations[name] = typ
        if typ is int:
            attrs[name] = 0
        elif typ is float:
            attrs[name] = 0.0
        else:
            attrs[name] = ""
    meta = type("Meta", (), {"table": table})
    cls = type(
        f"_M_{table}_{'_'.join(sorted(fields))}",
        (Model,),
        {"__annotations__": annotations, **attrs, "Meta": meta},
    )
    _known_mig_models[key] = cls
    return cls


def _o2o_pair(
    name,
    *,
    on_save,
    on_delete,
    on_update,
    fk_default=None,
) -> tuple[type, type, str]:
    """Build a one-to-one owner/child model pair for action testing."""
    fk = f"{name.lower()}_id"
    child_cls = type(
        f"{name}Detail",
        (Model,),
        {
            "__annotations__": {"id": str, fk: (str | None), "label": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: fk_default,
            "label": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str, "detail": child_cls},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
            "detail": OneToOne(
                child_cls,
                foreign_key=fk,
                on_save=on_save,
                on_delete=on_delete,
                on_update=on_update,
            ),
        },
    )
    return owner_cls, child_cls, fk


def _o2m_pair(
    name,
    *,
    on_save,
    on_delete,
    on_update,
    fk_default=None,
) -> tuple[type, type, str]:
    """Build a one-to-many owner/child model pair for action testing."""
    fk = f"{name.lower()}_id"
    child_cls = type(
        f"{name}Child",
        (Model,),
        {
            "__annotations__": {"id": str, fk: (str | None), "label": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: fk_default,
            "label": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str, "children": list[child_cls]},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
            "children": OneToMany(
                child_cls,
                foreign_key=fk,
                on_save=on_save,
                on_delete=on_delete,
                on_update=on_update,
            ),
        },
    )
    return owner_cls, child_cls, fk


def _m2o_pair(
    name,
    *,
    on_save,
) -> tuple[type, type, str]:
    """Build a many-to-one holder/parent model pair for action testing.

    The holder carries the foreign key and the ``ManyToOne`` relationship;
    many-to-one only supports ``on_save`` (delete/update are always no action).
    """
    fk = f"{name.lower()}_id"
    parent_cls = type(
        f"{name}Parent",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
        },
    )
    holder_cls = type(
        f"{name}Item",
        (Model,),
        {
            "__annotations__": {
                "id": str,
                fk: (str | None),
                "label": str,
                "parent": parent_cls,
            },
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: None,
            "label": "",
            "parent": ManyToOne(
                parent_cls,
                foreign_key=fk,
                on_save=on_save,
            ),
        },
    )
    return holder_cls, parent_cls, fk


def _mtm_pair(
    name,
    *,
    on_save,
) -> tuple[type, type, str]:
    """Build a many-to-many owner/target model pair for action testing.

    Many-to-many only supports ``on_save`` (delete/update are fixed to cascade
    and operate on the junction ``through`` table).
    """
    through = f"{name.lower()}_links"
    target_cls = type(
        f"{name}Role",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str, "items": list[target_cls]},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
            "items": ManyToMany(
                target_cls,
                through=through,
                on_save=on_save,
            ),
        },
    )
    return owner_cls, target_cls, through


# ---------------------------------------------------------------------------
# Lifecycle & schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_lifecycle_connect_health_disconnect(kind):
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    assert await adapter.health_check() is False
    await adapter.connect()
    assert await adapter.health_check() is True
    await adapter.disconnect()
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_schema_and_tables(kind):
    db = await database_for(kind)
    try:
        tables = await db.tables()
        names = {t.lower() for t in tables}
        assert any("users" in n for n in names), f"missing users among {names}"
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Repository CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_and_read(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        user = await repo.create(
            _u(
                "u1",
                "alice",
                name="Alice",
                age=30,
                profile=Profile(city="Tehran", street="one"),
            )
        )
        assert user.id is not None
        assert user.is_persisted is True

        fetched = await db.repository(User).where(User.username == "alice").first()
        assert fetched is not None
        assert fetched.name == "Alice"
        assert fetched.age == 30
        assert fetched.active is True
        assert fetched.id == "u1"

        fetched = await db.repository(User).where(User.profile.city == "Tehran").first()
        assert fetched is not None
        assert fetched.name == "Alice"
        assert fetched.age == 30
        assert fetched.active is True
        assert fetched.id == "u1"

        fetched = await db.repository(User).where(User.profile.city == "Fake").first()
        assert fetched is None
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_many(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        created = await repo.create_many(
            [
                _u("u1", "u1", name="One", age=20),
                _u("u2", "u2", name="Two", age=30),
                _u("u3", "u3", name="Three", age=40),
            ]
        )
        assert len(created) == 3
        assert all(u.id is not None for u in created)
        assert await repo.count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_save_insert_and_update(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        obj = _u("s1", "saved", name="First", age=5)
        await repo.save(obj)  # insert path
        assert obj.is_persisted is True

        obj.name = "Second"
        obj.age = 6
        await repo.save(obj)  # update path
        assert obj.is_dirty is False

        loaded = await repo.where(User.username == "saved").first()
        assert loaded is not None
        assert loaded.name == "Second"
        assert loaded.age == 6
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_update_many_rows(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("a", "a", age=10, active=True),
                _u("b", "b", age=20, active=True),
                _u("c", "c", age=30, active=False),
            ]
        )
        rows = await repo.update_many(User.active == True, values={"age": 99})
        assert rows == 2
        assert await repo.count(User.age == 99) == 2
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_update_single_row(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("su1", "su1", age=10, active=True),
                _u("su2", "su2", age=20, active=True),
            ]
        )

        rows = await repo.update(User.active == True, values={"age": 99})
        assert rows == 1
        assert (await repo.where(User.username == "su1").first()).age == 99
        assert (await repo.where(User.username == "su2").first()).age == 20
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_delete_single_row(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("sd1", "sd1", age=10, active=True),
                _u("sd2", "sd2", age=20, active=True),
            ]
        )

        rows = await repo.delete(User.active == True)
        assert rows == 1
        assert await repo.count(User.active == True) == 1

        remaining = await repo.query(User.active == True).all()
        assert {u.username for u in remaining} - {"sd1", "sd2"} == set()
        assert {u.username for u in remaining} != {"sd1", "sd2"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_delete_rows(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [_u(f"d{i}", f"d{i}", age=i, active=True) for i in range(3)]
        )
        rows = await repo.delete(User.username == "d0")
        assert rows == 1
        assert await repo.count() == 2
        assert await repo.count(User.username == "d0") == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_delete_many_rows(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("dm1", "dm1", age=10, active=True),
                _u("dm2", "dm2", age=20, active=True),
                _u("dm3", "dm3", age=30, active=False),
            ]
        )
        # ``delete_many`` removes every matching row (soft-deletes here, so they
        # leave the live count but remain visible with_deleted).
        rows = await repo.delete_many(User.active == True)
        assert rows == 2
        assert await repo.count() == 1
        assert await repo.count(User.active == True) == 0
        assert await repo.query().with_deleted().count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_limit_offset_ignored_for_update_delete(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("io1", "io1", age=10, active=True),
                _u("io2", "io2", age=20, active=True),
                _u("io3", "io3", age=30, active=False),
            ]
        )

        rows = (
            await repo.query(User.active == True).limit(1).offset(1).update({"age": 99})
        )
        assert rows == 2
        assert await repo.count(User.age == 99) == 2

        deleted = await repo.query(User.active == True).limit(1).offset(1).delete()
        assert deleted == 2
        assert await repo.count() == 1
        assert await repo.query().with_deleted().count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_upsert_insert_then_update(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        create = {"id": "x", "username": "up", "age": 1, "active": True}

        rows = await repo.upsert(
            conflict_target=("username",),
            create_values=create,
            update_values={"name": "Changed"},
        )
        assert rows == 1
        row = await repo.where(User.username == "up").first()
        assert row is not None
        assert row.id == "x"
        assert row.age == 1
        assert row.active is True

        rows2 = await repo.upsert(
            conflict_target=("username",),
            create_values=create,
            update_values={"name": "Changed2"},
        )
        assert rows2 in (1, 2)
        updated = await repo.where(User.username == "up").first()
        assert updated is not None
        assert updated.name == "Changed2"
        assert updated.age == 1
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_count_and_exists(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("c1", "c1", active=True),
                _u("c2", "c2", active=True),
                _u("c3", "c3", active=False),
            ]
        )
        assert await repo.count() == 3
        assert await repo.count(User.active == True) == 2
        assert await repo.exists(User.username == "c1") is True
        assert await repo.exists(User.username == "nope") is False
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_filters_and_ordering(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("bob", "bob", name="Bob", age=40, active=True),
                _u("ann", "ann", name="Ann", age=25, active=True),
                _u("cat", "cat", name="Cat", age=18, active=False),
            ]
        )

        rows = await repo.query(User.age >= 20).order_by(User.age.asc()).all()
        assert [u.username for u in rows] == ["ann", "bob"]

        first = await repo.query(User.active == True).order_by(User.age.desc()).first()
        assert first is not None
        assert first.username == "bob"

        assert len(await repo.query(User.username.in_(["bob", "cat"])).all()) == 2
        assert len(await repo.query(User.age.between(20, 45)).all()) == 2
        like = await repo.query(User.name.like("An%")).all()
        assert [u.username for u in like] == ["ann"]
        assert await repo.query(User.name.is_null()).count() == 0
        assert await repo.query(User.name.is_not_null()).count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_update_many(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("qu1", "qu1", age=10, active=True),
                _u("qu2", "qu2", age=20, active=True),
                _u("qu3", "qu3", age=30, active=False),
            ]
        )

        rows = await repo.query(User.active == True).update({"age": 99})
        assert rows == 2
        assert await repo.count(User.age == 99) == 2
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_delete_many(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("qd1", "qd1", age=10, active=True),
                _u("qd2", "qd2", age=20, active=True),
                _u("qd3", "qd3", age=30, active=False),
            ]
        )

        rows = await repo.query(User.active == True).delete()
        assert rows == 2
        assert await repo.count() == 1
        assert await repo.query().with_deleted().count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_upsert(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        create = {"id": "qu", "age": 5, "active": True}

        # ``Query.upsert`` via ``where`` inserts when the row is absent...
        rows = await repo.where(User.username == "qu").upsert(create)
        assert rows in (1, 2)
        row = await repo.where(User.username == "qu").first()
        assert row is not None
        assert row.id == "qu"
        assert row.age == 5

        # ...and updates it on a subsequent call.
        rows2 = await repo.where(User.username == "qu").upsert(
            {"id": "qu", "age": 9, "active": True}
        )
        assert rows2 in (1, 2)
        updated = await repo.where(User.username == "qu").first()
        assert updated is not None
        assert updated.age == 9
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_pagination(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many([_u(f"p{i:02d}", f"p{i:02d}", age=i) for i in range(5)])
        page = await repo.query().order_by(User.age.asc()).offset(1).limit(2).all()
        assert [u.username for u in page] == ["p01", "p02"]

        page1 = await repo.query().order_by(User.age.asc()).paginate(1, 2).all()
        page2 = await repo.query().order_by(User.age.asc()).paginate(2, 2).all()
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].username == "p00"
        assert page2[0].username == "p02"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_select_returns_dicts(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("s1", "s1", name="A", age=1),
                _u("s2", "s2", name="B", age=2),
            ]
        )
        sel = await repo.query().select(User.username).all()
        assert all(isinstance(r, dict) for r in sel)
        assert {r["username"] for r in sel} == {"s1", "s2"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_aggregations(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("g1", "g1", name="A", age=10, active=True),
                _u("g2", "g2", name="B", age=20, active=True),
                _u("g3", "g3", name="C", age=30, active=False),
            ]
        )
        row = (
            await repo.query()
            .aggregate(
                n=Count(User.id),
                total=Sum(User.age),
                avg=Avg(User.age),
                lo=Min(User.age),
                hi=Max(User.age),
            )
            .all()
        )
        assert len(row) == 1
        r = row[0]
        assert r["n"] == 3
        assert r["total"] == 60
        assert r["lo"] == 10
        assert r["hi"] == 30

        by_active = (
            await repo.query().group_by(User.active).aggregate(n=Count(User.id)).all()
        )
        counts = {r["active"]: r["n"] for r in by_active}
        assert counts[True] == 2
        assert counts[False] == 1
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_include_relationship(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        from tests.db._conformance import Profile

        await repo.create(
            User(
                id="home",
                username="home",
                name="Home",
                age=30,
                profile=Profile(street="100 Main", city="Oslo"),
                posts=[_p("p1", "keep", "home"), _p("p2", "drop", "home")],
            )
        )
        loaded = (
            await repo.query(User.username == "home")
            .include(Include(User.posts), User.profile)
            .all()
        )
        assert len(loaded) == 1
        user = loaded[0]
        assert user.profile.city == "Oslo"
        assert sorted(p.title for p in user.posts) == ["drop", "keep"]

        loaded = await repo.query(User.username == "home").all()
        assert len(loaded) == 1
        user = loaded[0]
        if repo.adapter.nested_documents:
            assert user.profile != None
        else:
            assert user.profile == None
        assert user.posts == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_include_filter_posts_returns_all_users(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("u1", "u1", age=1, posts=[_p("pp1", "keep", "u1")]),
                _u("u2", "u2", age=2, posts=[_p("pp2", "drop", "u2")]),
                _u("u3", "u3", age=3),
            ]
        )
        loaded = (
            await repo.query()
            .include(Include(User.posts, filter=Post.title == "keep"))
            .all()
        )

        assert len(loaded) == 3
        for row in loaded:
            assert all(p.title == "keep" for p in row.posts)
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Relationships: Embedded, EmbeddedMany, OneToOne, OneToMany, ManyToOne,
# ManyToMany.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_embedded_relationship(kind):
    db = await database_for(kind, [Item])
    try:
        repo = db.repository(Item)

        nested = db.adapter("primary").nested_documents
        tables = ["items"] + ([] if nested else ["items_address"])

        await repo.create(
            Item(
                id="e1",
                name="widget",
                address=Profile(street="one", city="two"),
            )
        )
        before = await _row_counts(db, *tables)
        expected_before = {"items": 1}
        if not nested:
            expected_before["items_address"] = 1
        assert before == expected_before, before

        loaded = (await repo.query().include(Item.address).all())[0]
        assert loaded.name == "widget"
        assert loaded.address.street == "one"
        assert loaded.address.city == "two"

        assert [row.id for row in await repo.query(Item.address.street == "one").all()] == ["e1"]
        assert [row.id for row in await repo.query(Item.address.city.in_("two")).all()] == ["e1"]

        await repo.delete(loaded)
        after = await _row_counts(db, *tables)
        assert after == {t: 0 for t in tables}, after
        assert await repo.count() == 0
    finally:
        await cleanup(db)


def _deep_embedded_tables(model: type, prefix: str | None = None) -> list[str]:
    """Return all flat-table names created by embedded relationships."""
    meta = model.metadata()
    tables: list[str] = []
    for rel_name, rel in meta.relationships.items():
        if not rel.is_embedded or rel.target in (dict, list):
            continue
        table = f"{prefix}_{rel_name}" if prefix else f"{meta.table}_{rel_name}"
        tables.append(table)
        tables.extend(_deep_embedded_tables(rel.target, table))
    return tables


def _deep_embedded_value() -> DeepEmbedded1:
    value: Any = DeepEmbedded7(value="embedded-7")
    for model in (
        DeepEmbedded6,
        DeepEmbedded5,
        DeepEmbedded4,
        DeepEmbedded3,
        DeepEmbedded2,
    ):
        value = model(child=value)
    return DeepEmbedded1(child=value)


def _deep_many_value() -> list[DeepMany1]:
    value: Any = DeepManyLeaf(value="many-leaf")
    for model in (
        DeepMany6,
        DeepMany5,
        DeepMany4,
        DeepMany3,
        DeepMany2,
    ):
        value = model(children=[value])
    return [DeepMany1(children=[value])]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_seven_level_embedded_and_embedded_many_relationships(kind):
    db = await database_for(kind, [DeepRoot])
    try:
        root_repo = db.repository(DeepRoot)
        root = DeepRoot(
            id="deep-1",
            embedded=_deep_embedded_value(),
            many=_deep_many_value(),
        )
        await root_repo.create(root)

        nested = db.adapter("primary").nested_documents
        embedded_tables = _deep_embedded_tables(DeepRoot)
        if nested:
            assert await _row_counts(db, "deeproots") == {"deeproots": 1}
        else:
            tables = ["deeproots", *embedded_tables]
            assert await _row_counts(db, *tables) == {table: 1 for table in tables}
            assert embedded_tables == [
                "deeproots_embedded",
                "deeproots_embedded_child",
                "deeproots_embedded_child_child",
                "deeproots_embedded_child_child_child",
                "deeproots_embedded_child_child_child_child",
                "deeproots_embedded_child_child_child_child_child",
                "deeproots_embedded_child_child_child_child_child_child",
                "deeproots_many",
                "deeproots_many_children",
                "deeproots_many_children_children",
                "deeproots_many_children_children_children",
                "deeproots_many_children_children_children_children",
                "deeproots_many_children_children_children_children_children",
                "deeproots_many_children_children_children_children_children_children",
            ]

        embedded_path = DeepRoot.embedded
        for _ in range(6):
            embedded_path = embedded_path.child
        assert [row.id for row in await root_repo.query(embedded_path.value == "embedded-7").all()] == ["deep-1"]

        many_path = DeepRoot.many
        for _ in range(6):
            many_path = many_path.children
        assert [row.id for row in await root_repo.query(many_path.value.in_("many-leaf")).all()] == ["deep-1"]

        if nested:
            loaded = (await root_repo.query().all())[0]
            assert loaded.id == "deep-1"
            embedded = loaded.embedded
            for _ in range(6):
                embedded = embedded["child"]
            assert embedded["value"] == "embedded-7"
            many = loaded.many[0]
            for _ in range(6):
                many = many["children"][0]
            assert many["value"] == "many-leaf"
        else:
            assert await _row_counts(db, *embedded_tables) == {
                table: 1 for table in embedded_tables
            }
            for table in embedded_tables:
                rows = await db.adapter("primary").execute_query(
                    QueryAST(
                        source=_row_count_model(table),
                        filters=(Path(_row_count_model(table), ("parent_id",)) == "deep-1",),
                    )
                )
                assert len(rows) == 1
                assert dict(rows[0])["parent_id"] == "deep-1"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_embedded_many_relationship(kind):
    db = await database_for(kind, [Item])
    try:
        repo = db.repository(Item)
        nested = db.adapter("primary").nested_documents
        tables = ["items"] + ([] if nested else ["items_tags"])

        await repo.create_many(
            [Item(id="m1", name="kit", tags=[Tag(name="a"), Tag(name="b")])]
        )
        before = await _row_counts(db, *tables)
        expected_before = {"items": 1}
        if not nested:
            expected_before["items_tags"] = 2
        assert before == expected_before, before

        loaded = (await repo.query().include(Item.tags).all())[0]
        assert sorted(t.name for t in loaded.tags) == ["a", "b"]

        assert [row.id for row in await repo.query(Item.tags.name == "a").all()] == ["m1"]
        assert [row.id for row in await repo.query(Item.tags.name.in_("b")).all()] == ["m1"]

        await repo.delete_many()
        after = await _row_counts(db, *tables)
        assert after == {t: 0 for t in tables}, after
        assert await repo.count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_one_to_one_relationship(kind):
    db = await database_for(kind, [Citizen, Passport])
    try:
        repo = db.repository(Citizen)
        await repo.create(
            Citizen(id="c1", name="alice", passport=Passport(id="p1", number="X123"))
        )
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }

        loaded = (await repo.query().include(Citizen.passport).all())[0]
        assert loaded.passport.number == "X123"

        # Deleting the citizen cascades the related passport row too.
        await repo.delete(loaded)
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 0,
            "passports": 0,
        }
        assert await db.repository(Passport).query().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_one_to_many_relationship(kind):
    db = await database_for(kind, [User, Post])
    try:
        repo = db.repository(User)
        await repo.create(
            _u("r1", "owner", age=1, posts=[_p("rp1", "x", "r1"), _p("rp2", "y", "r1")])
        )
        assert await _row_counts(db, "users", "posts") == {"users": 1, "posts": 2}

        loaded = (await repo.query().include(User.posts).all())[0]
        assert sorted(p.title for p in loaded.posts) == ["x", "y"]

        # ``User`` is soft-delete: the child posts are hard-cascaded away, while
        # the parent row is retained (marked deleted) rather than dropped. Both
        # effects happen across every adapter.
        await repo.delete(loaded)
        assert await _row_counts(db, "users", "posts") == {"users": 1, "posts": 0}
        assert await repo.count() == 0  # active view hides the soft-deleted row
        assert await db.repository(Post).query().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_one_relationship(kind):
    db = await database_for(kind, [Employee, Dept])
    try:
        emp_repo = db.repository(Employee)
        dept_repo = db.repository(Dept)
        await dept_repo.create(Dept(id="d1", name="eng"))
        await emp_repo.create(Employee(id="e1", name="bob", dept_id="d1"))
        assert await _row_counts(db, "employees", "depts") == {
            "employees": 1,
            "depts": 1,
        }

        loaded = (await emp_repo.query().include(Employee.dept).all())[0]
        assert loaded.dept.name == "eng"
    finally:
        await cleanup(db)


def _deep_relation_value(family_name: str):
    family = DEEP_RELATION_FAMILIES[family_name]
    relation_name = {
        "one_to_one": "child",
        "one_to_many": "children",
        "many_to_one": "parent",
        "many_to_many": "children",
    }[family_name]
    current: Any = family[-1](id=f"{family_name}-7")
    for model in reversed(family[:-1]):
        current = model(id=f"{family_name}-{len(family) - len(model.__name__)}", **{relation_name: [current] if relation_name in ("children",) else current})
    return current


def _deep_relation_include(family_name: str):
    family = DEEP_RELATION_FAMILIES[family_name]
    relation_name = {
        "one_to_one": "child",
        "one_to_many": "children",
        "many_to_one": "parent",
        "many_to_many": "children",
    }[family_name]
    nested = None
    for owner in reversed(family[:-1]):
        path = getattr(owner, relation_name)
        nested = Include(path) if nested is None else Include(path, nested=(nested,))
    return nested


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize("family_name", sorted(DEEP_RELATION_FAMILIES))
async def test_seven_level_relations_and_nested_queries(kind, family_name):
    family = DEEP_RELATION_FAMILIES[family_name]
    db = await database_for(kind, list(family))
    try:
        root_cls = family[0]
        root = _deep_relation_value(family_name)
        await db.repository(root_cls).create(root)

        tables = [model.metadata().table for model in family]
        if family_name == "many_to_many":
            tables.extend(
                rel.through
                for model in family[:-1]
                for rel in model.metadata().relationships.values()
                if rel.through
            )
        counts = await _row_counts(db, *tables)
        assert counts == {table: 1 for table in tables}

        include = _deep_relation_include(family_name)
        relation_name = {
            "one_to_one": "child",
            "one_to_many": "children",
            "many_to_one": "parent",
            "many_to_many": "children",
        }[family_name]
        path = getattr(root_cls, relation_name)
        for _ in range(5):
            path = getattr(path, relation_name)
        scalar_path = path.value
        scalar_matches = await db.repository(root_cls).query(scalar_path == f"{family_name.replace('_', '-')}-7").all()
        assert [row.id for row in scalar_matches] == [root.id]

        collection_path = getattr(root_cls, relation_name)
        for _ in range(5):
            collection_path = getattr(collection_path, relation_name)
        collection_matches = await db.repository(root_cls).query(
            collection_path.value.in_(f"{family_name.replace('_', '-')}-7")
        ).all()
        assert [row.id for row in collection_matches] == [root.id]

        loaded = (await db.repository(root_cls).query().include(include).all())[0]
        current = loaded
        relation_name = {
            "one_to_one": "child",
            "one_to_many": "children",
            "many_to_one": "parent",
            "many_to_many": "children",
        }[family_name]
        for _ in range(6):
            current = getattr(current, relation_name)
            if relation_name in ("children",):
                assert len(current) == 1
                current = current[0]
        assert current.value == f"{family_name.replace('_', '-')}-7"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_relationship(kind):
    db = await database_for(kind, [Employee, Role])
    try:
        emp_repo = db.repository(Employee)
        role_repo = db.repository(Role)

        rel = Employee.metadata().relationships["roles"]
        assert rel.kind == RelationshipKind.MANY_TO_MANY
        assert rel.through == "employee_roles"
        assert Role.metadata().table == "roles"

        await role_repo.create_many(
            [
                Role(id="r1", name="admin"),
                Role(id="r2", name="editor"),
                Role(id="r3", name="viewer"),
                Role(id="r4", name="owner"),
                Role(id="r5", name="guest"),
            ]
        )

        await emp_repo.create(
            Employee(
                id="e1",
                name="bob",
                roles=[Role(id="r1", name="admin"), Role(id="r2", name="editor")],
            )
        )

        # The junction table ``employee_roles`` captures the two links.
        assert await _row_counts(db, "employees", "roles", "employee_roles") == {
            "employees": 1,
            "roles": 5,
            "employee_roles": 2,
        }

        loaded = (await emp_repo.query().include(Employee.roles).all())[0]
        assert sorted(r.name for r in loaded.roles) == ["admin", "editor"]

        stored = await role_repo.query().all()
        assert {r.id for r in stored} == {"r1", "r2", "r3", "r4", "r5"}

        # Many-to-many is restrict: deleting an employee removes the junction
        # links and the employee row, but leaves the related roles intact.
        await emp_repo.delete(loaded)
        assert await _row_counts(db, "employees", "roles", "employee_roles") == {
            "employees": 0,
            "roles": 5,
            "employee_roles": 0,
        }
        assert {r.id for r in await role_repo.query().all()} == {
            "r1",
            "r2",
            "r3",
            "r4",
            "r5",
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_filter_sort_limit_skip(kind):
    db = await database_for(kind, [Employee, Role])
    try:
        emp_repo = db.repository(Employee)
        role_repo = db.repository(Role)

        await role_repo.create_many(
            [
                Role(id="r1", name="admin"),
                Role(id="r2", name="editor"),
                Role(id="r3", name="viewer"),
                Role(id="r4", name="owner"),
                Role(id="r5", name="guest"),
            ]
        )
        await emp_repo.create_many(
            [
                Employee(
                    id="e1",
                    name="alice",
                    roles=[Role(id="r1", name="admin"), Role(id="r2", name="editor")],
                ),
                Employee(
                    id="e2",
                    name="bob",
                    roles=[Role(id="r1", name="admin"), Role(id="r3", name="viewer")],
                ),
                Employee(
                    id="e3",
                    name="carol",
                    roles=[Role(id="r5", name="guest")],
                ),
            ]
        )

        # Sort the parent query, skip one, limit to two; roles stay attached.
        rows = await (
            emp_repo.query()
            .order_by(Employee.name)
            .offset(1)
            .limit(2)
            .include(Employee.roles)
            .all()
        )
        assert [r.name for r in rows] == ["bob", "carol"]
        assert sorted(r.name for r in rows[0].roles) == ["admin", "viewer"]
        assert [r.name for r in rows[1].roles] == ["guest"]

        # Filter the parent query; each returned employee keeps its roles.
        rows = await (
            emp_repo.query(Employee.name == "alice").include(Employee.roles).all()
        )
        assert len(rows) == 1
        assert rows[0].id == "e1"
        assert sorted(r.name for r in rows[0].roles) == ["admin", "editor"]

        # The include filter narrows the loaded roles per employee.
        rows = (
            await emp_repo.query(Employee.name == "alice")
            .include(Include(Employee.roles, filter=Role.name == "editor"))
            .all()
        )
        assert len(rows) == 1
        assert [r.name for r in rows[0].roles] == ["editor"]

        # Combine a parent filter with an include filter across employees.
        rows = (
            await emp_repo.query(Employee.name.in_(["alice", "bob"]))
            .order_by(Employee.name)
            .include(Include(Employee.roles, filter=Role.name == "admin"))
            .all()
        )
        assert [r.name for r in rows] == ["alice", "bob"]
        assert all([r.name for r in row.roles] == ["admin"] for row in rows)
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Cascades: on update & on delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_update_one_to_many(kind):
    db = await database_for(kind, [User, Post])
    try:
        await db.repository(User).create(
            _u("u1", "owner", age=1, posts=[_p("p1", "x", "u1"), _p("p2", "y", "u1")])
        )

        owner = (await db.repository(User).query().include(User.posts).all())[0]
        owner.id = "u2"
        await db.repository(User).save(owner)

        posts = await db.repository(Post).query().order_by(Post.title).all()
        assert {p.id for p in posts} == {"p1", "p2"}
        assert all(p.user_id == "u2" for p in posts)
        assert await db.repository(Post).query().count() == 2
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_update_one_to_one(kind):
    db = await database_for(kind, [Citizen, Passport])
    try:
        await db.repository(Citizen).create(
            Citizen(id="c1", name="alice", passport=Passport(id="p1", number="X123"))
        )

        # Changing the parent id cascades to the one-to-one child foreign key.
        citizen = (
            await db.repository(Citizen).query().include(Citizen.passport).all()
        )[0]
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }

        citizen.id = "c2"
        await db.repository(Citizen).save(citizen)

        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }
        passports = await db.repository(Passport).query().all()
        assert len(passports) == 1
        assert passports[0].citizen_id == "c2"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_delete_one_to_one(kind):
    db = await database_for(kind, [Citizen, Passport])
    try:
        repo = db.repository(Citizen)
        await repo.create_many(
            [
                Citizen(
                    id="c1",
                    name="alice",
                    passport=Passport(id="p1", number="X123"),
                ),
                Citizen(
                    id="c2",
                    name="bob",
                    passport=Passport(id="p2", number="Y456"),
                ),
            ]
        )

        loaded = (await repo.query().include(Citizen.passport).all())[0]
        await repo.delete(loaded)

        # Deleting one citizen cascades only that citizen's passport.
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }
        remaining = await db.repository(Passport).query().all()
        assert {p.id for p in remaining} in ({"p1"}, {"p2"})
        assert await db.repository(Citizen).query().count() == 1
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_delete_one_to_many_isolates_siblings(kind):
    db = await database_for(kind, [User, Post])
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u(
                    "r1",
                    "owner1",
                    age=1,
                    posts=[_p("p1", "x", "r1"), _p("p2", "y", "r1")],
                ),
                _u("r2", "owner2", age=2, posts=[_p("p3", "z", "r2")]),
            ]
        )

        loaded = (await repo.query(User.id == "r1").include(User.posts).all())[0]
        await repo.delete(loaded)

        assert (await db.repository(Post).query().all())[0].user_id == "r2"
        assert await db.repository(Post).query().count() == 1
        assert await db.repository(Post).exists(Post.id == "p3") is True
        assert await db.repository(Post).exists(Post.id == "p1") is False
        assert await repo.query(User.id == "r2").count() == 1
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_one_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    owner, child, _fk = _o2o_pair(
        name,
        on_save=action.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=ReferentialAction.CASCADE.value,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(owner(id="p1", name="p", detail=child(id="d1", label="x")))
        child_count = await db.repository(child).query().count()
        if action is SaveAction.CASCADE:
            assert child_count == 1
        else:
            assert child_count == 0
        assert await _row_counts(db, owner_table, child_table) == {
            owner_table: 1,
            child_table: child_count,
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_one_on_delete(kind, action):
    name = "OnDelete" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2o_pair(
        name,
        on_save=SaveAction.CASCADE.value,
        on_delete=action.value,
        on_update=ReferentialAction.CASCADE.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(owner(id="p1", name="p", detail=child(id="d1", label="x")))
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await repo.query().include(owner.detail).all())[0]
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await repo.delete(loaded)
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await repo.delete(loaded)
            children = await db.repository(child).query().all()
            after = {
                owner_table: await repo.query().count(),
                child_table: len(children),
            }
            if action is ReferentialAction.CASCADE:
                assert after == {owner_table: 0, child_table: 0}
            else:
                assert after == {owner_table: 0, child_table: 1}
                if action is ReferentialAction.SET_NULL:
                    assert getattr(children[0], fk) is None
                elif action is ReferentialAction.SET_DEFAULT:
                    assert getattr(children[0], fk) == "unknown"
                else:
                    assert getattr(children[0], fk) == "p1"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_one_on_update(kind, action):
    name = "OnUpdate" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2o_pair(
        name,
        on_save=SaveAction.NO_ACTION.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=action.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        await db.repository(child).create(child(id="d1", label="x", **{fk: "p1"}))
        await db.repository(owner).create(owner(id="p1", name="p"))
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await db.repository(owner).query().include(owner.detail).all())[0]
        loaded.id = "p2"
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await db.repository(owner).save(loaded)
            stored = (await db.repository(owner).query().all())[0]
            assert stored.id == "p1"
            children = await db.repository(child).query().all()
            assert len(children) == 1
            assert getattr(children[0], fk) == "p1"
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await db.repository(owner).save(loaded)
            children = await db.repository(child).query().all()
            assert len(children) == 1
            if action is ReferentialAction.CASCADE:
                assert getattr(children[0], fk) == "p2"
            elif action is ReferentialAction.SET_NULL:
                assert getattr(children[0], fk) is None
            elif action is ReferentialAction.SET_DEFAULT:
                assert getattr(children[0], fk) == "unknown"
            else:
                assert getattr(children[0], fk) == "p1"
            assert await _row_counts(db, owner_table, child_table) == before
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_many_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    owner, child, _fk = _o2m_pair(
        name,
        on_save=action.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=ReferentialAction.CASCADE.value,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                children=[
                    child(id="d1", label="x"),
                    child(id="d2", label="y"),
                    child(id="d3", label="z"),
                ],
            )
        )
        child_count = await db.repository(child).query().count()
        if action is SaveAction.CASCADE:
            assert child_count == 3
        else:
            assert child_count == 0
        assert await _row_counts(db, owner_table, child_table) == {
            owner_table: 1,
            child_table: child_count,
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_many_on_delete(kind, action):
    name = "OnDelete" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2m_pair(
        name,
        on_save=SaveAction.CASCADE.value,
        on_delete=action.value,
        on_update=ReferentialAction.CASCADE.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                children=[
                    child(id="d1", label="x"),
                    child(id="d2", label="y"),
                    child(id="d3", label="z"),
                ],
            )
        )
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await repo.query().include(owner.children).all())[0]
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await repo.delete(loaded)
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await repo.delete(loaded)
            children = await db.repository(child).query().all()
            after = {
                owner_table: await repo.query().count(),
                child_table: len(children),
            }
            if action is ReferentialAction.CASCADE:
                assert after == {owner_table: 0, child_table: 0}
            else:
                assert after == {owner_table: 0, child_table: 3}
                if action is ReferentialAction.SET_NULL:
                    assert all(getattr(c, fk) is None for c in children)
                elif action is ReferentialAction.SET_DEFAULT:
                    assert all(getattr(c, fk) == "unknown" for c in children)
                else:
                    assert all(getattr(c, fk) == "p1" for c in children)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_many_on_update(kind, action):
    name = "OnUpdate" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2m_pair(
        name,
        on_save=SaveAction.NO_ACTION.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=action.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        await db.repository(child).create_many(
            [
                child(id="d1", label="x", **{fk: "p1"}),
                child(id="d2", label="y", **{fk: "p1"}),
                child(id="d3", label="z", **{fk: "p1"}),
            ]
        )
        await db.repository(owner).create(owner(id="p1", name="p"))
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await db.repository(owner).query().include(owner.children).all())[0]
        loaded.id = "p2"
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await db.repository(owner).save(loaded)
            stored = (await db.repository(owner).query().all())[0]
            assert stored.id == "p1"
            children = await db.repository(child).query().all()
            assert len(children) == 3
            assert all(getattr(c, fk) == "p1" for c in children)
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await db.repository(owner).save(loaded)
            children = await db.repository(child).query().all()
            assert len(children) == 3
            if action is ReferentialAction.CASCADE:
                assert all(getattr(c, fk) == "p2" for c in children)
            elif action is ReferentialAction.SET_NULL:
                assert all(getattr(c, fk) is None for c in children)
            elif action is ReferentialAction.SET_DEFAULT:
                assert all(getattr(c, fk) == "unknown" for c in children)
            else:
                assert all(getattr(c, fk) == "p1" for c in children)
            assert await _row_counts(db, owner_table, child_table) == before
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_many_to_one_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    holder, parent, fk = _m2o_pair(name, on_save=action.value)
    holder_table = holder.metadata().table
    parent_table = parent.metadata().table
    db = await database_for(kind, [holder, parent])
    try:
        repo = db.repository(holder)
        await repo.create_many(
            [
                holder(id="c1", label="x", parent=parent(id="p1", name="p")),
                holder(id="c2", label="y", parent=parent(id="p1", name="p")),
                holder(id="c3", label="z", parent=parent(id="p1", name="p")),
            ]
        )
        parent_count = await db.repository(parent).query().count()
        if action is SaveAction.CASCADE:
            assert parent_count == 1
        else:
            assert parent_count == 0
        assert await _row_counts(db, holder_table, parent_table) == {
            holder_table: 3,
            parent_table: parent_count,
        }
        stored = await repo.query().all()
        if action is SaveAction.CASCADE:
            assert all(getattr(o, fk) == "p1" for o in stored)
        else:
            assert all(getattr(o, fk) is None for o in stored)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_one_on_delete(kind):
    name = "OnDelete"
    holder, parent, fk = _m2o_pair(name, on_save=SaveAction.NO_ACTION.value)
    holder_table = holder.metadata().table
    parent_table = parent.metadata().table
    db = await database_for(kind, [holder, parent])
    try:
        await db.repository(parent).create(parent(id="p1", name="p"))
        await db.repository(holder).create_many(
            [
                holder(id="c1", label="x", **{fk: "p1"}),
                holder(id="c2", label="y", **{fk: "p1"}),
                holder(id="c3", label="z", **{fk: "p1"}),
            ]
        )
        before = await _row_counts(db, holder_table, parent_table)
        loaded = (await db.repository(holder).query().all())[0]
        await db.repository(holder).delete(loaded)
        after = await _row_counts(db, holder_table, parent_table)
        assert after == {holder_table: 2, parent_table: 1}
        holders = await db.repository(holder).query().all()
        assert len(holders) == 2
        assert all(getattr(h, fk) == "p1" for h in holders)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_one_on_update(kind):
    name = "OnUpdate"
    holder, parent, fk = _m2o_pair(name, on_save=SaveAction.NO_ACTION.value)
    holder_table = holder.metadata().table
    parent_table = parent.metadata().table
    db = await database_for(kind, [holder, parent])
    try:
        await db.repository(parent).create(parent(id="p1", name="p"))
        await db.repository(holder).create_many(
            [
                holder(id="c1", label="x", **{fk: "p1"}),
                holder(id="c2", label="y", **{fk: "p1"}),
                holder(id="c3", label="z", **{fk: "p1"}),
            ]
        )
        before = await _row_counts(db, holder_table, parent_table)
        loaded = await db.repository(holder).query().first()
        await db.repository(holder).query(holder.id == "c1").update({"id": "cp"})
        loaded = await db.repository(holder).query(holder.id == "cp").first()
        assert loaded.id == "cp"
        assert loaded.label == "x"
        assert await _row_counts(db, holder_table, parent_table) == before
        holders = await db.repository(holder).query().all()
        assert len(holders) == 3
        assert all(getattr(h, fk) == "p1" for h in holders)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_many_to_many_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    owner, target, through = _mtm_pair(name, on_save=action.value)
    owner_table = owner.metadata().table
    target_table = target.metadata().table
    db = await database_for(kind, [owner, target])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                items=[target(id="r1", name="a"), target(id="r2", name="b")],
            )
        )
        target_count = await db.repository(target).query().count()
        if action is SaveAction.CASCADE:
            assert target_count == 2
        else:
            assert target_count == 0
        assert await _row_counts(db, owner_table, target_table, through) == {
            owner_table: 1,
            target_table: target_count,
            through: target_count,
        }
        loaded = (await repo.query().include(owner.items).all())[0]
        if action is SaveAction.CASCADE:
            assert sorted(i.name for i in loaded.items) == ["a", "b"]
        else:
            assert loaded.items == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_on_delete(kind):
    name = "OnDelete"
    owner, target, through = _mtm_pair(name, on_save=SaveAction.CASCADE.value)
    owner_table = owner.metadata().table
    target_table = target.metadata().table
    db = await database_for(kind, [owner, target])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                items=[target(id="r1", name="a"), target(id="r2", name="b")],
            )
        )
        before = await _row_counts(db, owner_table, target_table, through)
        assert before == {owner_table: 1, target_table: 2, through: 2}
        loaded = (await repo.query().all())[0]
        await repo.delete(loaded)
        assert await _row_counts(db, owner_table, target_table, through) == {
            owner_table: 0,
            target_table: 2,
            through: 0,
        }
        assert await repo.query().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_on_update(kind):
    name = "OnUpdate"
    owner, target, through = _mtm_pair(name, on_save=SaveAction.CASCADE.value)
    owner_table = owner.metadata().table
    target_table = target.metadata().table
    db = await database_for(kind, [owner, target])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                items=[target(id="r1", name="a"), target(id="r2", name="b")],
            )
        )
        loaded = (await repo.query().include(owner.items).all())[0]
        loaded.items = [target(id="r1", name="a")]
        await repo.save(loaded)
        assert await _row_counts(db, owner_table, target_table, through) == {
            owner_table: 1,
            target_table: 2,
            through: 1,
        }
        reloaded = (await repo.query().include(owner.items).all())[0]
        assert sorted(i.name for i in reloaded.items) == ["a"]
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Cascades: on update & on delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_soft_delete_visibility(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(SoftUser)
        s1 = await repo.create(SoftUser(id="sd1", username="sd1"))
        await repo.create(SoftUser(id="sd2", username="sd2"))

        await repo.delete(s1)

        assert await repo.query().count() == 1
        assert await repo.query().with_deleted().count() == 2
        assert await repo.query().only_deleted().count() == 1
        only = await repo.query().only_deleted().first()
        assert only is not None
        assert only.username == "sd1"
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Hard delete (physical removal even for soft-delete models)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_hard_delete_many_ignores_soft_delete(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)  # soft_delete enabled
        await repo.create_many(
            [
                _u("hd1", "hd1", age=1),
                _u("hd2", "hd2", age=2),
            ]
        )

        # A normal delete soft-deletes: the row remains visible with_deleted.
        one = await repo.delete(User.username == "hd1")
        assert one == 1
        assert await repo.query().with_deleted().count() == 2

        # Hard delete physically removes it even though it is soft-deleted.
        removed = await repo.hard_delete_many(User.username == "hd1")
        assert removed == 1
        assert await repo.query().with_deleted().count() == 1
        assert await repo.query().only_deleted().count() == 0

        # Hard deletes a live row too.
        removed2 = await repo.hard_delete_many(User.username == "hd2")
        assert removed2 == 1
        assert await repo.query().with_deleted().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_hard_delete_object_and_query(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        obj = await repo.create(
            _u("hd3", "hd3", age=3, posts=[_p("hp1", "post", "hd3")])
        )

        rows = await repo.hard_delete(obj)
        assert rows == 1
        assert await repo.query().with_deleted().count() == 0
        assert await db.repository(Post).query().count() == 0

        # Query.hard_delete() terminal method.
        await repo.create(_u("hd4", "hd4", age=4))
        qr = await repo.query(User.username == "hd4").hard_delete()
        assert qr == 1
        assert await repo.query().with_deleted().count() == 0
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Transactions & unit of work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_transaction_commit_and_rollback(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)

        async with db.transaction() as tx:
            await db.repository(User).create(_u("txc", "txc", age=1))

        assert await repo.exists(User.username == "txc") is True

        async with db.transaction() as tx:
            await db.repository(User).create(_u("txr", "txr", age=2))
            await tx.rollback()

        assert await repo.exists(User.username == "txr") is False

        try:
            async with db.transaction() as tx:
                await db.repository(User).create(_u("txr", "txr", age=2))
                raise RuntimeError("test")
        except Exception:
            pass
        assert await repo.exists(User.username == "txr") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_commit_across_repositories(kind):
    db = await database_for(kind)
    adapter = db.adapter("primary")
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        repo = db.repository(User)
        async with db.unit_of_work() as uow:
            assert uow.is_active is True
            assert uow.is_committed is False

            u_users = uow.repository(User)
            u_posts = uow.repository(Post)
            await u_users.create(_u("uw1", "uw1", age=7))
            await u_posts.create(Post(id="up1", title="uow post", user_id="uw1"))
            await u_users.create(_u("uw2", "uw2", age=8))

            assert uow.users is u_users
            assert uow.posts is u_posts

            await uow.commit()
            assert uow.is_committed is True

        assert await repo.exists(User.username == "uw1") is True
        assert await repo.exists(User.username == "uw2") is True
        assert transaction_calls == [None]
        posts = await db.repository(Post).where(Post.user_id == "uw1").all()
        assert len(posts) == 1
        assert posts[0].title == "uow post"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_rollback_on_uncommitted_exit(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(_u("uwr1", "uwr1", age=1))
            await uow.repository(User).create(_u("uwr2", "uwr2", age=2))

        assert await repo.exists(User.username == "uwr1") is False
        assert await repo.exists(User.username == "uwr2") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_rollback_on_exception(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        with pytest.raises(RuntimeError):
            async with db.unit_of_work() as uow:
                await uow.repository(User).create(_u("uwx1", "uwx1", age=1))
                await uow.repository(User).create(_u("uwx2", "uwx2", age=2))
                raise RuntimeError("boom")

        assert await repo.exists(User.username == "uwx1") is False
        assert await repo.exists(User.username == "uwx2") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_explicit_rollback(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(_u("uwz1", "uwz1", age=1))
            await uow.rollback()
            assert uow.is_committed is False
        assert await repo.exists(User.username == "uwz1") is False
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Transactions & unit of work
#
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_cross_repository_atomic_commit(kind):
    db = await database_for(kind)
    adapter = db.adapter("primary")
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        async with db.unit_of_work() as uow:
            users = uow.repository(User)
            posts = uow.repository(Post)
            await users.create(
                _u(
                    "a1",
                    "alice",
                    name="Alice",
                    age=30,
                    profile=Profile(city="Tehran", street="one"),
                )
            )
            await posts.create_many(
                [_p("ap1", "Alice first post", "a1"), _p("ap2", "Alice two post", "a1")]
            )
            await uow.commit()

        assert transaction_calls == [None]
        assert await db.repository(User).count() == 1
        assert await db.repository(Post).count() == 2
        assert await db.repository(User).exists(User.username == "alice") is True

        alice = (
            await db.repository(User)
            .query(User.username == "alice")
            .include(User.profile)
            .all()
        )[0]
        assert alice.profile.city == "Tehran"
        assert alice.profile.street == "one"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_cross_repository_rollback_on_error(kind):
    db = await database_for(kind)
    try:
        with pytest.raises(ValueError, match="Simulated transfer failure"):
            async with db.unit_of_work() as uow:
                await uow.repository(User).create(
                    _u(
                        "b1",
                        "bob",
                        name="Bob",
                        age=40,
                        profile=Profile(city="Shiraz", street="two"),
                    )
                )
                await uow.repository(Post).create(_p("bp1", "Bob post", "b1"))
                raise ValueError("Simulated transfer failure")

        assert await db.repository(User).count() == 0
        assert await db.repository(Post).count() == 0
        assert await _row_counts(db, "users", "posts") == {
            "users": 0,
            "posts": 0,
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_auto_rollback_on_uncommitted_exit(kind):
    db = await database_for(kind)
    try:
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(
                _u(
                    "c1",
                    "charlie",
                    name="Charlie",
                    age=35,
                    profile=Profile(city="Isfahan", street="four"),
                )
            )

        assert uow.is_active is False
        assert await db.repository(User).count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_committed_row_visibility(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        await db.repository(User).create(
            _u(
                "v1",
                "visible",
                name="Visible",
                age=1,
                profile=Profile(city="Tabriz", street="five"),
            )
        )
        assert await db.repository(User).count() == 1
        rows = (
            await db.repository(User)
            .query(User.username == "visible")
            .include(User.profile)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].name == "Visible"
        assert rows[0].profile.city == "Tabriz"
        assert rows[0].profile.street == "five"
        assert adapter._in_active_transaction() is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_rollback_and_transaction_commit(kind):
    db = await database_for(kind)
    adapter = db.adapter("primary")
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(
                _u(
                    "u1",
                    "bob",
                    name="Bob",
                    age=40,
                    profile=Profile(city="Mashhad", street="six"),
                )
            )
        assert transaction_calls == [None]
        assert await db.repository(User).count() == 0

        async with db.transaction():
            await db.repository(User).create(
                _u(
                    "o1",
                    "outer",
                    name="Outer",
                    age=50,
                    profile=Profile(city="Yazd", street="seven"),
                )
            )

        assert transaction_calls == [None, None]
        rows = (
            await db.repository(User)
            .query(User.username == "outer")
            .include(User.profile)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].name == "Outer"
        assert rows[0].profile.city == "Yazd"
    finally:
        await cleanup(db)


# --- Nested transactions / no-transaction block ---------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_no_transaction_reports_inactive(kind):
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    assert adapter._in_active_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_marker_set_reports_active(kind):
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    adapter._tx_session = object()
    try:
        assert adapter._in_active_transaction() is True
    finally:
        adapter._tx_session = None
    assert adapter._in_active_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_lone_mutation_auto_commits_without_transaction(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        assert adapter._in_active_transaction() is False

        await db.repository(User).create(
            _u(
                "auto",
                "auto",
                name="Auto",
                age=1,
                profile=Profile(city="Kerman", street="eight"),
            )
        )
        assert await db.repository(User).count() == 1
        assert await db.repository(User).exists(User.username == "auto") is True
        assert adapter._in_active_transaction() is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_transaction_not_supported(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)

        async with db.transaction():
            assert adapter._in_active_transaction() is True
            await repo.create(
                _u("outer", "outer", age=1, profile=Profile(city="Arak", street="nine"))
            )

            with pytest.raises(Exception):
                async with db.transaction():
                    await repo.create(_u("inner", "inner", age=2))

            assert adapter._in_active_transaction() is True

        assert adapter._in_active_transaction() is False
        assert await repo.exists(User.username == "outer") is True
        assert await repo.exists(User.username == "inner") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_transaction_outer_survives_rejection(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)

        async with db.transaction():
            await repo.create(
                _u(
                    "persist",
                    "persist",
                    age=1,
                    profile=Profile(city="Rasht", street="ten"),
                )
            )
            try:
                async with db.transaction():
                    await repo.create(_u("inner-fail", "inner-fail", age=2))
            except Exception:
                pass

            assert adapter._in_active_transaction() is True
            await repo.create(_u("after-fail", "after-fail", age=3))

        assert adapter._in_active_transaction() is False
        usernames = {u.username for u in await repo.query().all()}
        assert usernames == {"persist", "after-fail"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_in_transaction_error(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)
        await repo.create(
            _u("persist", "persist", age=1, profile=Profile(city="Rasht", street="ten"))
        )
        with pytest.raises(ValueError, match="Simulated transfer failure"):
            async with db.transaction():
                u1 = await repo.query(User.profile.city == "Rasht").update(
                    {"name": "Ali"}
                )
                u1 = await repo.query(User.profile.city == "Rasht").first()
                assert u1.name == "Ali"
                raise ValueError("Simulated transfer failure")

        assert adapter._in_active_transaction() is False
        usernames = {u.username for u in await repo.query().all()}
        assert usernames == {"persist"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_in_transaction_read(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        transaction_calls: list[None] = []
        original_factory = adapter.transaction_factory

        def transaction_factory():
            transaction_calls.append(None)
            return original_factory()

        adapter.transaction_factory = transaction_factory
        repo = db.repository(User)
        await repo.create(
            _u("persist", "persist", age=1, profile=Profile(city="Rasht", street="ten"))
        )
        expected_calls_before_transaction = 0 if adapter.nested_documents else 1
        assert transaction_calls == [None] * expected_calls_before_transaction
        async with db.transaction():
            assert transaction_calls == [None] * (expected_calls_before_transaction + 1)
            u1 = await repo.query(User.profile.city == "Rasht").update({"name": "Ali"})
            u1 = await repo.query(User.profile.city == "Rasht").first()
            assert u1.name == "Ali"

        assert adapter._in_active_transaction() is False
        assert transaction_calls == [None] * (expected_calls_before_transaction + 1)
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_duplicate_key_translation(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create(_u("dup", "dup", age=1))
        with pytest.raises(DuplicateKeyError):
            await repo.create(_u("dup", "dup", age=2))
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_connect_is_idempotent(kind):
    """Calling ``connect()`` twice must be a safe no-op on an open pool."""
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    await adapter.connect()
    await adapter.connect()
    assert await adapter.health_check() is True
    await adapter.disconnect()
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_reconnect_after_disconnect(kind):
    """A pool torn down by ``disconnect()`` can be re-established by ``connect()``."""
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    await adapter.connect()
    assert await adapter.health_check() is True
    await adapter.disconnect()
    assert await adapter.health_check() is False

    await adapter.connect()
    assert await adapter.health_check() is True
    await adapter.disconnect()
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_context_manager(kind):
    """Using ``Database`` as an async context manager releases the pool on exit."""
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    async with Database(adapter):
        assert await adapter.health_check() is True
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_shared_across_repositories(kind):
    """Repositories on one ``Database`` share the same pooled connection."""
    db = await database_for(kind)
    try:
        await db.repository(User).create(_u("cp_shared", "cp_shared", age=7))
        observed = await db.repository(User).where(User.username == "cp_shared").all()
        assert len(observed) == 1
        assert observed[0].age == 7

        count = await db.repository(User).where(User.username == "cp_shared").count()
        assert count == 1
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Backup & restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_backup_and_restore_roundtrip_all_tables(kind, tmp_path):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create(
            _u(
                "b1",
                "b1",
                name="Backy",
                age=31,
                profile=Profile(
                                    city="Tehran",
                                    street="main",
                                    contact=Contact(phone="123456789", version=Version(name="contact-v1")),
                                    version=Version(name="profile-v1"),
                                ),
            )
        )
        await repo.create(
            _u(
                "b2",
                "b2",
                name="Resty",
                age=32,
                profile=Profile(city="Shiraz", street="second"),
            )
        )
        await db.repository(Post).create(_p("bp1", "backup post", "b1"))

        backup_path = str(tmp_path / "backup")
        counts = await db.backup(path=backup_path)

        assert counts["users"] == 2
        assert counts["posts"] == 1
        ls = ["users.json", "posts.json"]
        if not db.adapter("primary").nested_documents:
            embedded_tables = {
                "users_profile": 2,
                "users_profile_contact": 1,
                "users_profile_version": 1,
                "users_profile_contact_version": 1,
            }
            ls.extend(f"{table}.json" for table in embedded_tables)
            for table, expected_count in embedded_tables.items():
                assert counts[table] == expected_count
        for name in ls:
            assert os.path.exists(os.path.join(backup_path, name)), (
                f"missing backup {name}"
            )

        # A stray row added after the backup must be discarded on restore
        # because ``restore`` drops existing rows before re-importing.
        await repo.create(_u("b_extra", "b_extra", age=99))

        restored = await db.restore(path=backup_path)
        assert restored["users"] == 2
        assert restored["posts"] == 1
        if not db.adapter("primary").nested_documents:
            assert restored["users_profile"] == 2
            assert restored["users_profile_contact"] == 1
            assert restored["users_profile_version"] == 1
            assert restored["users_profile_contact_version"] == 1

        usernames = {u.username for u in await repo.query().all()}
        assert usernames == {"b1", "b2"}

        rows = await repo.query(User.username == "b1").include(User.profile).all()
        assert len(rows) == 1
        b1 = rows[0]
        assert b1.name == "Backy"
        assert b1.age == 31
        assert b1.profile.city == "Tehran"

        posts = await db.repository(Post).where(Post.user_id == "b1").all()
        assert len(posts) == 1
        assert posts[0].title == "backup post"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_backup_and_restore_selected_tables(kind, tmp_path):
    db = await database_for(kind)
    try:
        await db.repository(User).create_many(
            [_u("s1", "s1", age=1), _u("s2", "s2", age=2)]
        )
        await db.repository(Post).create(_p("sp1", "untouched", "s1"))

        backup_path = str(tmp_path / "only_users")
        counts = await db.backup(path=backup_path, tables=["users"])
        assert counts == {"users": 2}
        assert os.listdir(backup_path) == ["users.json"]

        # Restoring only ``users`` must repopulate it (dropping any extras)
        # while leaving ``posts`` alone.
        await db.repository(User).create(_u("s_extra", "s_extra", age=99))
        restored = await db.restore(path=backup_path, tables=["users"])
        assert restored == {"users": 2}

        usernames = {u.username for u in await db.repository(User).query().all()}
        assert usernames == {"s1", "s2"}

        posts = await db.repository(Post).where(Post.user_id == "s1").all()
        assert len(posts) == 1
        assert posts[0].title == "untouched"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_restore_without_drop_existing(kind, tmp_path):
    src = await database_for(kind)
    try:
        await src.repository(User).create(_u("r1", "r1", age=1))
        backup_path = str(tmp_path / "append")
        await src.backup(path=backup_path, tables=["users"])
    finally:
        await cleanup(src)

    # A fresh database starts empty; restoring with ``drop_existing=False``
    # appends the backed-up rows into it.
    dst = await database_for(kind)
    try:
        restored = await dst.restore(
            path=backup_path, tables=["users"], drop_existing=False
        )
        assert restored == {"users": 1}
        users = await dst.repository(User).query().all()
        assert [u.username for u in users] == ["r1"]
    finally:
        await cleanup(dst)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_backup_and_restore_with_pagination(kind, tmp_path):
    db = await database_for(kind)
    try:
        await db.repository(User).create_many(
            [_u(f"pg{i:02d}", f"pg{i:02d}", age=i) for i in range(25)]
        )

        backup_path = str(tmp_path / "paginated")
        counts = await db.backup(path=backup_path, tables=["users"], page_size=10)
        assert counts == {"users": 25}

        await db.repository(User).delete_many()
        assert await db.repository(User).query().count() == 0

        restored = await db.restore(path=backup_path, tables=["users"], chunk_size=10)
        assert restored == {"users": 25}

        ages = sorted(u.age for u in await db.repository(User).query().all())
        assert ages == list(range(25))
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_lifecycle(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_create_accounts.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_accounts", [
        Column("id", "str", primary_key=True),
        Column("owner", "str", nullable=False),
        Column("balance", "float", default=0.0),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_accounts")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_add_index.py").write_text(
            """async def upgrade(adapter):
    await adapter.create_index("mn_accounts", ["owner"], name="idx_mn_owner")

async def downgrade(adapter):
    await adapter.drop_index("mn_accounts", "idx_mn_owner")
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_accounts" not in await _table_names(db)

        scaffold = mm.create("add audit to accounts")
        assert scaffold.name == "0003_add_audit_to_accounts.py"
        assert scaffold.exists()
        content = scaffold.read_text(encoding="utf-8")
        assert "async def upgrade(adapter)" in content
        assert "async def downgrade(adapter)" in content

        statuses = await mm.status()
        assert len(statuses) == 3
        assert not any(s.applied for s in statuses)
        assert all(s.checksum for s in statuses)

        applied = await mm.upgrade()
        assert applied == [
            "0001_create_accounts",
            "0002_add_index",
            "0003_add_audit_to_accounts",
        ]

        statuses = await mm.status()
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)
        assert all(s.checksum for s in statuses)

        assert "mn_accounts" in await _table_names(db)

        Account = _mig_model("mn_accounts", {"owner": str, "balance": float})
        repo = db.repository(Account)
        await repo.create(Account(id="a1", owner="alice", balance=10.5))
        rows = await repo.query().all()
        assert len(rows) == 1
        assert rows[0].owner == "alice"
        assert rows[0].balance == 10.5

        assert await mm.check() is True

        reapply = await mm.upgrade()
        assert reapply == []

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_create_accounts",
            "0002_add_index",
            "0003_add_audit_to_accounts",
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_checksum_tampering(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        first = mig_dir / "0001_initial.py"
        first.write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_safe", [Column("id", "int", primary_key=True)])

async def downgrade(adapter):
    await adapter.drop_table("mn_safe")
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_safe" not in await _table_names(db)

        applied = await mm.upgrade()
        assert applied == ["0001_initial"]
        assert "mn_safe" in await _table_names(db)
        assert await mm.check() is True

        records = await mm.tracker.get_applied_migrations()
        assert [r.version for r in records] == ["0001_initial"]
        assert all(r.checksum for r in records)

        first.write_text(
            """# TAMPERED
async def upgrade(adapter):
    pass

async def downgrade(adapter):
    pass
""",
            encoding="utf-8",
        )

        with pytest.raises(MigrationChecksumError):
            await mm.check()

        with pytest.raises(MigrationChecksumError):
            await mm.upgrade()
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_downgrade_and_reset(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        for i in range(1, 4):
            (mig_dir / f"{i:04d}_step_{i}.py").write_text(
                f"""from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_step_{i}", [Column("id", "int", primary_key=True)])

async def downgrade(adapter):
    await adapter.drop_table("mn_step_{i}")
""",
                encoding="utf-8",
            )

        mm = MigrationManager(db, path=mig_dir)

        assert not {"mn_step_1", "mn_step_2", "mn_step_3"} & await _table_names(db)

        applied = await mm.upgrade()
        assert applied == ["0001_step_1", "0002_step_2", "0003_step_3"]

        names = await _table_names(db)
        assert {"mn_step_1", "mn_step_2", "mn_step_3"} <= names

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_step_1",
            "0002_step_2",
            "0003_step_3",
        }

        reverted = await mm.downgrade(1)
        assert reverted == ["0003_step_3"]

        statuses = await mm.status()
        assert statuses[0].applied
        assert statuses[1].applied
        assert not statuses[2].applied

        names = await _table_names(db)
        assert "mn_step_1" in names
        assert "mn_step_2" in names
        assert "mn_step_3" not in names

        reverted_rest = await mm.reset()
        assert reverted_rest == ["0002_step_2", "0001_step_1"]

        statuses = await mm.status()
        assert not any(s.applied for s in statuses)

        names = await _table_names(db)
        assert not {"mn_step_1", "mn_step_2", "mn_step_3"} & names

        records = await mm.tracker.get_applied_migrations()
        assert records == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_column_operations_with_data(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_base.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_cols", [
        Column("id", "str", primary_key=True),
        Column("name", "str", nullable=False),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_cols")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_add_column.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.add_column("mn_cols", Column("age", "int", default=18))

async def downgrade(adapter):
    await adapter.drop_column("mn_cols", "age")
""",
            encoding="utf-8",
        )

        (mig_dir / "0003_rename_column.py").write_text(
            """async def upgrade(adapter):
    await adapter.rename_column("mn_cols", "name", "full_name")

async def downgrade(adapter):
    await adapter.rename_column("mn_cols", "full_name", "name")
""",
            encoding="utf-8",
        )

        (mig_dir / "0004_drop_column.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.drop_column("mn_cols", "full_name")

async def downgrade(adapter):
    await adapter.add_column("mn_cols", Column("full_name", "str", nullable=True))
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_cols" not in await _table_names(db)

        assert await mm.upgrade(target="0001") == ["0001_base"]
        assert "mn_cols" in await _table_names(db)

        Base = _mig_model("mn_cols", {"name": str})
        repo = db.repository(Base)
        await repo.create(Base(id="r1", name="Alice"))
        before = await repo.query().all()
        assert len(before) == 1
        assert before[0].name == "Alice"

        assert await mm.upgrade(target="0002") == ["0002_add_column"]
        WithAge = _mig_model("mn_cols", {"name": str, "age": int})
        rows = await db.repository(WithAge).query().all()
        assert len(rows) == 1
        assert rows[0].name == "Alice"
        assert rows[0].age == 18

        assert await mm.upgrade(target="0003") == ["0003_rename_column"]
        Renamed = _mig_model("mn_cols", {"full_name": str, "age": int})
        rows = await db.repository(Renamed).query().all()
        assert len(rows) == 1
        assert rows[0].full_name == "Alice"
        assert rows[0].age == 18

        assert await mm.upgrade(target="0004") == ["0004_drop_column"]
        Dropped = _mig_model(
            "mn_cols",
            {
                "age": int,
                "full_name": str,
            },
        )
        rows = await db.repository(Dropped).query().all()
        assert len(rows) == 1
        assert rows[0].age == 18
        assert rows[0].full_name == ""

        statuses = await mm.status()
        assert len(statuses) == 4
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_base",
            "0002_add_column",
            "0003_rename_column",
            "0004_drop_column",
        }

        reverted = await mm.reset()
        assert len(reverted) == 4
        assert "mn_cols" not in await _table_names(db)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_drop_and_rename_table_with_data(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_people.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_people", [
        Column("id", "str", primary_key=True),
        Column("name", "str", nullable=False),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_people")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_rename_table.py").write_text(
            """async def upgrade(adapter):
    await adapter.rename_table("mn_people", "mn_citizens")

async def downgrade(adapter):
    await adapter.rename_table("mn_citizens", "mn_people")
""",
            encoding="utf-8",
        )

        (mig_dir / "0003_drop_table.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.drop_table("mn_citizens")

async def downgrade(adapter):
    await adapter.create_table("mn_citizens", [
        Column("id", "str", primary_key=True),
        Column("name", "str", nullable=False),
    ])
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert not {"mn_people", "mn_citizens"} & await _table_names(db)

        assert await mm.upgrade(target="0001") == ["0001_people"]
        assert "mn_people" in await _table_names(db)

        People = _mig_model("mn_people", {"name": str})
        repo = db.repository(People)
        await repo.create_many(
            [People(id="p1", name="Alice"), People(id="p2", name="Bob")]
        )
        before = await repo.query().all()
        assert len(before) == 2
        assert {r.name for r in before} == {"Alice", "Bob"}

        assert await mm.upgrade(target="0002") == ["0002_rename_table"]
        assert "mn_people" not in await _table_names(db)
        assert "mn_citizens" in await _table_names(db)

        Citizens = _mig_model("mn_citizens", {"name": str})
        after_rename = await db.repository(Citizens).query().all()
        assert len(after_rename) == 2
        assert {r.name for r in after_rename} == {"Alice", "Bob"}

        assert await mm.upgrade(target="0003") == ["0003_drop_table"]
        assert "mn_citizens" not in await _table_names(db)

        statuses = await mm.status()
        assert len(statuses) == 3
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_people",
            "0002_rename_table",
            "0003_drop_table",
        }

        reverted = await mm.reset()
        assert len(reverted) == 3
        assert not {"mn_people", "mn_citizens"} & await _table_names(db)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_create_and_drop_index_with_data(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_items.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_items", [
        Column("id", "str", primary_key=True),
        Column("email", "str", nullable=False),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_items")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_create_index.py").write_text(
            """async def upgrade(adapter):
    await adapter.create_index("mn_items", ["email"], unique=True, name="idx_mn_email")

async def downgrade(adapter):
    await adapter.drop_index("mn_items", "idx_mn_email")
""",
            encoding="utf-8",
        )

        (mig_dir / "0003_drop_index.py").write_text(
            """async def upgrade(adapter):
    await adapter.drop_index("mn_items", "idx_mn_email")

async def downgrade(adapter):
    await adapter.create_index("mn_items", ["email"], unique=True, name="idx_mn_email")
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_items" not in await _table_names(db)

        assert await mm.upgrade(target="0001") == ["0001_items"]
        assert "mn_items" in await _table_names(db)

        Item = _mig_model("mn_items", {"email": str})
        repo = db.repository(Item)
        await repo.create_many(
            [Item(id="i1", email="a@x.com"), Item(id="i2", email="b@x.com")]
        )
        before = await repo.query().all()
        assert len(before) == 2
        assert {i.email for i in before} == {"a@x.com", "b@x.com"}

        assert await mm.upgrade(target="0002") == ["0002_create_index"]
        after_create = await repo.query().all()
        assert len(after_create) == 2
        assert {i.email for i in after_create} == {"a@x.com", "b@x.com"}

        assert await mm.upgrade(target="0003") == ["0003_drop_index"]
        after_drop = await repo.query().all()
        assert len(after_drop) == 2
        assert {i.email for i in after_drop} == {"a@x.com", "b@x.com"}

        statuses = await mm.status()
        assert len(statuses) == 3
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_items",
            "0002_create_index",
            "0003_drop_index",
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_auto_generates_identity_object_id(kind):
    from bson import ObjectId

    from tests.db._conformance import adapter_for

    Config._cache["database"] = SimpleNamespace(ID=ObjectId)

    class User(Model):
        id: ID = Field(
            database=DatabaseField(primary_key=True, generated=True, default_factory=ID)
        )
        name: str
        p_id: ID = Field(database=DatabaseField(generated=False, default=ID()))
        token: UUID = Field(
            database=DatabaseField(generated=True, default_factory=uuid4)
        )

    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema([User])
    try:
        user = await db.repository(User).create(User(name="smko"))
        assert isinstance(user.id, ID)
        assert isinstance(user.p_id, ID)
        assert isinstance(user.token, UUID)

        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched is not None
        assert isinstance(fetched.p_id, ID)
        assert isinstance(fetched.token, UUID)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_auto_generates_identity_str(kind):
    from tests.db._conformance import adapter_for

    Config._cache["database"] = SimpleNamespace(ID=str)

    class User(Model):
        id: ID = Field(
            database=DatabaseField(primary_key=True, generated=True, default_factory=ID)
        )
        name: str
        p_id: ID = Field(database=DatabaseField(generated=False, default=ID()))
        token: UUID = Field(
            database=DatabaseField(generated=True, default_factory=uuid4)
        )

    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema([User])
    try:
        user = await db.repository(User).create(User(name="smko"))
        assert isinstance(user.id, ID)
        assert isinstance(user.p_id, ID)
        assert isinstance(user.token, UUID)

        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched is not None
        assert isinstance(fetched.p_id, ID)
        assert isinstance(fetched.token, UUID)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_auto_generates_identity_int(kind):
    from tests.db._conformance import adapter_for

    Config._cache["database"] = SimpleNamespace(ID=int)

    class User(Model):
        id: ID = Field(
            database=DatabaseField(primary_key=True, generated=True, auto_inc=True)
        )
        name: str
        p_id: ID = Field(database=DatabaseField(generated=False, default=ID(2)))
        token: UUID = Field(
            database=DatabaseField(generated=True, default_factory=uuid4)
        )

    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema([User])
    try:
        user = await db.repository(User).create(User(name="smko"))
        assert isinstance(user.id, ID)
        assert isinstance(user.p_id, ID)
        assert isinstance(user.token, UUID)
        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched.id.value == 1
        user = await db.repository(User).create(User(name="smko"))
        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched is not None
        assert isinstance(fetched.p_id, ID)
        assert isinstance(fetched.token, UUID)
        assert fetched.id.value == 2
    finally:
        await cleanup(db)


@pytest.mark.parametrize("kind", ADAPTERS)
def test_auto_inc_requires_primary_key(kind):
    Config._cache["database"] = SimpleNamespace(ID=int)

    with pytest.raises(ValueError, match="auto_inc=True must be primary_key=True"):

        class InvalidView(Model):
            id: str = Field(database=DatabaseField(primary_key=True))
            views: int = Field(database=DatabaseField(generated=True, auto_inc=True))


def test_auto_inc_requires_integer_field():
    from renus.db.mongodb.compiler import MongoCompiler
    from renus.db.mutation import Insert

    class InvalidView(Model):
        id: str = Field(
            database=DatabaseField(primary_key=True, generated=True, auto_inc=True)
        )

    with pytest.raises(ValueError, match="must have type int or ID"):
        MongoCompiler().compile_mutation(Insert(InvalidView, {}))


def test_auto_inc_requires_integer_config():
    from renus.db.mongodb.compiler import MongoCompiler
    from renus.db.mutation import Insert

    Config._cache["database"] = SimpleNamespace(ID=str)

    class InvalidConfigView(Model):
        id: ID = Field(
            database=DatabaseField(primary_key=True, generated=True, auto_inc=True)
        )

    with pytest.raises(ValueError, match=r"Config\('database'\)\.ID=int"):
        MongoCompiler().compile_mutation(Insert(InvalidConfigView, {}))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_single_table_create_does_not_start_transaction(kind):
    from tests.db._conformance import adapter_for

    class PlainRecord(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        name: str

    adapter = adapter_for(kind)
    db = Database(adapter)
    await db.connect()
    await db.create_schema([PlainRecord])
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        await db.repository(PlainRecord).create(
            PlainRecord(id="plain-1", name="single table")
        )
        assert transaction_calls == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_relationship_create_starts_transaction_only_for_multiple_tables(kind):
    from tests.db._conformance import adapter_for

    class RelatedRecord(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        name: str
        profile: Profile = Embedded(Profile)

    adapter = adapter_for(kind)
    db = Database(adapter)
    await db.connect()
    await db.create_schema([RelatedRecord])
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        await db.repository(RelatedRecord).create(
            RelatedRecord(
                id="related-1",
                name="relationship",
                profile=Profile(city="Tehran", street="one"),
            )
        )
        expected_calls = 0 if adapter.nested_documents else 1
        assert len(transaction_calls) == expected_calls
    finally:
        await cleanup(db)
