"""Conformance suite: the standard operations every adapter must support.

Each test here runs against every registered adapter driver (see
``tests/db/_conformance.py``). A new backend joins the suite by registering an
``AdapterDriver``; if it passes this whole module it is correctly implemented
for the standard Renus database operations.

Run with::

    venv/bin/python -m pytest tests/db/test_adapter_conformance.py
"""

import os

import pytest

from renus.db import (
    Avg,
    Count,
    Database,
    DatabaseField,
    DuplicateKeyError,
    Field,
    Include,
    IntegrityError,
    LoadingStrategy,
    ManyToMany,
    ManyToOne,
    Max,
    Min,
    OneToMany,
    OneToOne,
    ReModel,
    ReferentialAction,
    RelationshipKind,
    SaveAction,
    Sum,
)

from tests.db._conformance import (
    Citizen,
    Dept,
    Employee,
    Item,
    Passport,
    Post,
    Profile,
    Role,
    SoftUser,
    Tag,
    User,
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
    """Return a lightweight model bound to an existing table/collection.
    """
    model = _row_count_models.get(table)
    if model is None:
        meta = type("Meta", (), {"table": table})
        model = type(f"_RowCount_{table}", (ReModel,), {"Meta": meta})
        _row_count_models[table] = model
    return model


async def _row_counts(db, *tables: str) -> dict[str, int]:
    """Return the number of rows stored in each table/collection.
    """
    return {t: await db.repository(_row_count_model(t)).count() for t in tables}


def _o2o_pair(
    name,
    *,
    on_save,
    on_delete,
    on_update,
    fk_default=None,
) -> tuple[type, type, str]:
    """Build a one-to-one owner/child model pair for action testing.
    """
    fk = f"{name.lower()}_id"
    child_cls = type(
        f"{name}Detail",
        (ReModel,),
        {
            "__annotations__": {"id": str, fk: (str | None), "label": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: fk_default,
            "label": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (ReModel,),
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
    """Build a one-to-many owner/child model pair for action testing.
    """
    fk = f"{name.lower()}_id"
    child_cls = type(
        f"{name}Child",
        (ReModel,),
        {
            "__annotations__": {"id": str, fk: (str | None), "label": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: fk_default,
            "label": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (ReModel,),
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
        (ReModel,),
        {
            "__annotations__": {"id": str, "name": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
        },
    )
    holder_cls = type(
        f"{name}Item",
        (ReModel,),
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
        (ReModel,),
        {
            "__annotations__": {"id": str, "name": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (ReModel,),
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
        await db.disconnect()


# ---------------------------------------------------------------------------
# Repository CRUD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_and_read(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        user = await repo.create(_u("u1", "alice", name="Alice", age=30,profile=Profile(city="Tehran",street="one")))
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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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

        rows = await repo.query(User.active == True).limit(1).offset(1).update({"age": 99})
        assert rows == 2
        assert await repo.count(User.age == 99) == 2

      
        deleted = await repo.query(User.active == True).limit(1).offset(1).delete()
        assert deleted == 2
        assert await repo.count() == 1
        assert await repo.query().with_deleted().count() == 3
    finally:
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        rows2 = await repo.where(User.username == "qu").upsert({"id": "qu", "age": 9, "active": True})
        assert rows2 in (1, 2)
        updated = await repo.where(User.username == "qu").first()
        assert updated is not None
        assert updated.age == 9
    finally:
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        row = await repo.query().aggregate(
            n=Count(User.id),
            total=Sum(User.age),
            avg=Avg(User.age),
            lo=Min(User.age),
            hi=Max(User.age),
        ).all()
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
        await db.disconnect()


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
        loaded = await repo.query(User.username == "home").include(
            Include(User.posts), User.profile
        ).all()
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
        await db.disconnect()


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
        loaded = await repo.query().include(
            Include(User.posts, filter=Post.title == "keep")
        ).all()
        
        assert len(loaded) == 3
        for row in loaded:
            assert all(p.title == "keep" for p in row.posts)
    finally:
        await db.disconnect()


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


        await repo.delete(loaded)
        after = await _row_counts(db, *tables)
        assert after == {t: 0 for t in tables}, after
        assert await repo.count() == 0
    finally:
        await db.disconnect()


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

        await repo.delete_many()
        after = await _row_counts(db, *tables)
        assert after == {t: 0 for t in tables}, after
        assert await repo.count() == 0
    finally:
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        rows = await emp_repo.query(Employee.name == "alice").include(
            Include(Employee.roles, filter=Role.name == "editor")
        ).all()
        assert len(rows) == 1
        assert [r.name for r in rows[0].roles] == ["editor"]

        # Combine a parent filter with an include filter across employees.
        rows = await emp_repo.query(Employee.name.in_(["alice", "bob"])).order_by(
            Employee.name
        ).include(Include(Employee.roles, filter=Role.name == "admin")).all()
        assert [r.name for r in rows] == ["alice", "bob"]
        assert all([r.name for r in row.roles] == ["admin"] for row in rows)
    finally:
        await db.disconnect()



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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_update_one_to_one(kind):
    db = await database_for(kind, [Citizen, Passport])
    try:
        await db.repository(Citizen).create(
            Citizen(id="c1", name="alice", passport=Passport(id="p1", number="X123"))
        )

        # Changing the parent id cascades to the one-to-one child foreign key.
        citizen = (await db.repository(Citizen).query().include(Citizen.passport).all())[0]
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
        await db.disconnect()


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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_delete_one_to_many_isolates_siblings(kind):
    db = await database_for(kind, [User, Post])
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("r1", "owner1", age=1, posts=[_p("p1", "x", "r1"), _p("p2", "y", "r1")]),
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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.repository(holder).query(
            holder.id == "c1"
        ).update({"id":"cp"})
        loaded=await db.repository(holder).query(holder.id == "cp").first()
        assert loaded.id == "cp"
        assert loaded.label == "x"
        assert await _row_counts(db, holder_table, parent_table) == before
        holders = await db.repository(holder).query().all()
        assert len(holders) == 3
        assert all(getattr(h, fk) == "p1" for h in holders)
    finally:
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_hard_delete_object_and_query(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        obj = await repo.create(_u("hd3", "hd3", age=3, posts=[_p("hp1", "post", "hd3")]))

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
        await db.disconnect()


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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_commit_across_repositories(kind):
    db = await database_for(kind)
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
        posts = await db.repository(Post).where(Post.user_id == "uw1").all()
        assert len(posts) == 1
        assert posts[0].title == "uow post"
    finally:
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


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
        await db.disconnect()


# ---------------------------------------------------------------------------
# Transactions & unit of work
#
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_cross_repository_atomic_commit(kind):
    db = await database_for(kind)
    try:
        async with db.unit_of_work() as uow:
            users = uow.repository(User)
            posts = uow.repository(Post)
            await users.create(
                _u("a1", "alice", name="Alice", age=30, profile=Profile(city="Tehran", street="one"))
            )
            await posts.create_many([_p("ap1", "Alice first post", "a1"),_p("ap2", "Alice two post", "a1")])
            await uow.commit()

        assert await db.repository(User).count() == 1
        assert await db.repository(Post).count() == 2
        assert await db.repository(User).exists(User.username == "alice") is True

        alice = (
            await db.repository(User).query(User.username == "alice").include(User.profile).all()
        )[0]
        assert alice.profile.city == "Tehran"
        assert alice.profile.street == "one"
    finally:
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_cross_repository_rollback_on_error(kind):
    db = await database_for(kind)
    try:
        with pytest.raises(ValueError, match="Simulated transfer failure"):
            async with db.unit_of_work() as uow:
                await uow.repository(User).create(
                    _u("b1", "bob", name="Bob", age=40, profile=Profile(city="Shiraz", street="two"))
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
        await db.disconnect()



@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_auto_rollback_on_uncommitted_exit(kind):
    db = await database_for(kind)
    try:
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(
                _u("c1", "charlie", name="Charlie", age=35, profile=Profile(city="Isfahan", street="four"))
            )

        assert uow.is_active is False
        assert await db.repository(User).count() == 0
    finally:
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_committed_row_visibility(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        await db.repository(User).create(
            _u("v1", "visible", name="Visible", age=1, profile=Profile(city="Tabriz", street="five"))
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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_rollback_and_transaction_commit(kind):
    db = await database_for(kind)
    try:
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(
                _u("u1", "bob", name="Bob", age=40, profile=Profile(city="Mashhad", street="six"))
            )
        assert await db.repository(User).count() == 0

        async with db.transaction():
            await db.repository(User).create(
                _u("o1", "outer", name="Outer", age=50, profile=Profile(city="Yazd", street="seven"))
            )

        rows = (
            await db.repository(User).query(User.username == "outer").include(User.profile).all()
        )
        assert len(rows) == 1
        assert rows[0].name == "Outer"
        assert rows[0].profile.city == "Yazd"
    finally:
        await db.disconnect()


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
            _u("auto", "auto", name="Auto", age=1, profile=Profile(city="Kerman", street="eight"))
        )
        assert await db.repository(User).count() == 1
        assert await db.repository(User).exists(User.username == "auto") is True
        assert adapter._in_active_transaction() is False
    finally:
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_transaction_not_supported(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)

        async with db.transaction():
            assert adapter._in_active_transaction() is True
            await repo.create(_u("outer", "outer", age=1, profile=Profile(city="Arak", street="nine")))

            with pytest.raises(Exception):
                async with db.transaction():
                    await repo.create(_u("inner", "inner", age=2))

            assert adapter._in_active_transaction() is True

        assert adapter._in_active_transaction() is False
        assert await repo.exists(User.username == "outer") is True
        assert await repo.exists(User.username == "inner") is False
    finally:
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_transaction_outer_survives_rejection(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)

        async with db.transaction():
            await repo.create(
                _u("persist", "persist", age=1, profile=Profile(city="Rasht", street="ten"))
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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_in_transaction_read(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)
        await repo.create(
            _u("persist", "persist", age=1, profile=Profile(city="Rasht", street="ten"))
        )
        with pytest.raises(ValueError, match="Simulated transfer failure"):
            async with db.transaction():
                u1=await repo.query(User.profile.city=="Rasht").update({"name":"Ali"})
                u1=await repo.query(User.profile.city=="Rasht").first()
                assert u1.name == "Ali"
                raise ValueError("Simulated transfer failure")
            

        assert adapter._in_active_transaction() is False
        usernames = {u.username for u in await repo.query().all()}
        assert usernames == {"persist"}
    finally:
        await db.disconnect()

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
        await db.disconnect()


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
        await db.disconnect()


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
                profile=Profile(city="Tehran", street="main"),
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
        ls=["users.json", "posts.json"]
        if not db.adapter("primary").nested_documents:
            ls.append("users_profile.json")
            assert counts["users_profile"] == 2
        for name in ls:
            assert os.path.exists(os.path.join(backup_path, name)), f"missing backup {name}"
       

        # A stray row added after the backup must be discarded on restore
        # because ``restore`` drops existing rows before re-importing.
        await repo.create(_u("b_extra", "b_extra", age=99))

        restored = await db.restore(path=backup_path)
        assert restored["users"] == 2
        assert restored["posts"] == 1
        if not db.adapter("primary").nested_documents:
            assert restored["users_profile"] == 2

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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_backup_and_restore_selected_tables(kind, tmp_path):
    db = await database_for(kind)
    try:
        await db.repository(User).create_many([_u("s1", "s1", age=1), _u("s2", "s2", age=2)])
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
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_restore_without_drop_existing(kind, tmp_path):
    src = await database_for(kind)
    try:
        await src.repository(User).create(_u("r1", "r1", age=1))
        backup_path = str(tmp_path / "append")
        await src.backup(path=backup_path, tables=["users"])
    finally:
        await src.disconnect()

    # A fresh database starts empty; restoring with ``drop_existing=False``
    # appends the backed-up rows into it.
    dst = await database_for(kind)
    try:
        restored = await dst.restore(path=backup_path, tables=["users"], drop_existing=False)
        assert restored == {"users": 1}
        users = await dst.repository(User).query().all()
        assert [u.username for u in users] == ["r1"]
    finally:
        await dst.disconnect()


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
        await db.disconnect()
