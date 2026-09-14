"""Conformance suite: the standard operations every adapter must support.

Each test here runs against every registered adapter driver (see
``tests/db/_conformance.py``). A new backend joins the suite by registering an
``AdapterDriver``; if it passes this whole module it is correctly implemented
for the standard Renus database operations.

Run with::

    venv/bin/python -m pytest tests/db/test_adapter_conformance.py
"""

import pytest

from renus.db import (
    Avg,
    Count,
    DuplicateKeyError,
    Include,
    Max,
    Min,
    RelationshipKind,
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
        await repo.create(
            Item(
                id="e1",
                name="widget",
                address=Profile(street="one", city="two"),
            )
        )
        loaded = (await repo.query().include(Item.address).all())[0]
        assert loaded.name == "widget"
        assert loaded.address.street == "one"
        assert loaded.address.city == "two"

        # Deleting the parent cascades the embedded child row.
        await repo.delete(loaded)
        assert await repo.count() == 0
    finally:
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_embedded_many_relationship(kind):
    db = await database_for(kind, [Item])
    try:
        repo = db.repository(Item)
        await repo.create_many(
            [Item(id="m1", name="kit", tags=[Tag(name="a"), Tag(name="b")])]
        )
        loaded = (await repo.query().include(Item.tags).all())[0]
        assert sorted(t.name for t in loaded.tags) == ["a", "b"]

        await repo.delete_many()
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
        loaded = (await repo.query().include(Citizen.passport).all())[0]
        assert loaded.passport.number == "X123"

        await repo.delete(loaded)
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
        loaded = (await repo.query().include(User.posts).all())[0]
        assert sorted(p.title for p in loaded.posts) == ["x", "y"]

        await repo.delete(loaded)
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

        loaded = (await emp_repo.query().include(Employee.roles).all())[0]
        assert sorted(r.name for r in loaded.roles) == ["admin", "editor"]

        stored = await role_repo.query().all()
        assert {r.id for r in stored} == {"r1", "r2", "r3", "r4", "r5"}

        # Many-to-many is restrict: deleting an employee removes the links but
        # leaves the related roles intact.
        await emp_repo.delete(loaded)
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
# Soft delete
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
