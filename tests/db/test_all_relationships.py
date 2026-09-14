from __future__ import annotations

import os

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Embedded,
    EmbeddedMany,
    Field,
    ManyToMany,
    ManyToOne,
    OneToMany,
    OneToOne,
    ReModel,
    Reference,
    RelationshipKind,
    SQLiteAdapter,
)

class Address(ReModel):
    street: str
    city: str

class Tag(ReModel):
    name: str

class Profile(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    account_id: str = ""
    bio: str

class Post(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    account_id: str = ""
    title: str

class Item(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: Address = Embedded(Address)
    tags: list[Tag] = EmbeddedMany(Tag)

class Department(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

class Account(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    profile: Profile = OneToOne(Profile, foreign_key="account_id", cascade=("all",))
    posts: list[Post] = OneToMany(Post, foreign_key="account_id", cascade=("all",))

class Employee(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    dept_id: str = ""
    dept: Department = ManyToOne(Department, foreign_key="dept_id")
    manager: Department = Reference(Department, foreign_key="dept_id")
    roles: list["Role"] = ManyToMany("Role", through="employee_roles")

class Role(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

MONGO_URI = "mongodb://localhost:27017"
MONGO_DB = f"renus_relationships_{os.getpid()}"

def _mongo_ready() -> bool:
    try:
        import pymongo

        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False

def _drop_mongo() -> None:
    try:
        import pymongo

        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        client.drop_database(MONGO_DB)
        client.close()
    except Exception:
        pass

def make_adapter(kind: str):
    if kind == "sqlite":
        return SQLiteAdapter({"database": ":memory:"})
    from renus.db import MongoDBAdapter

    return MongoDBAdapter({"uri": MONGO_URI, "database": MONGO_DB})

def is_mongo(db: Database) -> bool:
    return db.adapter("primary").name == "mongodb"

BACKENDS = [
    "sqlite",
    pytest.param(
        "mongodb",
        marks=pytest.mark.skipif(not _mongo_ready(), reason="MongoDB not reachable"),
    ),
]

async def connect_schema(kind: str, models: list[type]):
    db = Database(make_adapter(kind))
    await db.connect()
    await db.create_schema(models)
    return db

async def assert_created_tables(kind: str, db: Database, expected: set[str]) -> None:
    created = set(await db.tables())
    missing = set(expected) - created
    assert not missing, f"tables/collections not created: {missing} in {created}"

async def native_all(kind: str, db: Database, name: str) -> list[dict]:
    if is_mongo(db):
        coll = db.adapter("primary")._mongo_db[name]
        return [dict(d) for d in await coll.find({}).to_list(length=None)]

    conn = db.adapter("primary")._sqlite_db
    return [dict(r) for r in conn.execute(f"SELECT * FROM [{name}] ORDER BY 1;").fetchall()]

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_embedded_tables_persist_load_and_cascade(kind):
    db = await connect_schema(kind, [Item])
    try:
        item = db.repository(Item)
        await item.create(
            Item(id="1", name="widget", address=Address(street="one", city="two"))
        )

        if is_mongo(db):
            await assert_created_tables(kind, db, {"items"})
            doc = (await native_all(kind, db, "items"))[0]
            assert doc["address"] == {"street": "one", "city": "two", "id": None}
            assert set(doc) >= {"_id", "address"}
        else:
            await assert_created_tables(kind, db, {"items", "items_address"})
            addr_rows = await native_all(kind, db, "items_address")
            assert len(addr_rows) == 1
            assert addr_rows[0]["street"] == "one"
            assert addr_rows[0]["city"] == "two"
            assert addr_rows[0]["parent_id"] == "1"

        loaded = (await item.query().include(Item.address).all())[0]
        assert loaded.name == "widget"
        assert loaded.address.street == "one"
        assert loaded.address.city == "two"

        await item.delete(loaded)
        assert len(await item.query().all()) == 0
        if not is_mongo(db):
            assert await native_all(kind, db, "items_address") == []
        else:
            assert (await native_all(kind, db, "items")) == []
    finally:
        await db.disconnect()
        _drop_mongo()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_embedded_many_tables_persist_load_and_cascade(kind):
    db = await connect_schema(kind, [Item])
    try:
        item = db.repository(Item)
        await item.create(
            Item(id="1", name="kit", tags=[Tag(name="a"), Tag(name="b"), Tag(name="c")])
        )

        if is_mongo(db):
            await assert_created_tables(kind, db, {"items"})
            doc = (await native_all(kind, db, "items"))[0]
            assert [t["name"] for t in doc["tags"]] == ["a", "b", "c"]
        else:
            await assert_created_tables(kind, db, {"items", "items_tags"})
            tag_rows = await native_all(kind, db, "items_tags")
            assert [r["name"] for r in tag_rows] == ["a", "b", "c"]
            assert all(r["parent_id"] == "1" for r in tag_rows)

        loaded = (await item.query().include(Item.tags).all())[0]
        assert [t.name for t in loaded.tags] == ["a", "b", "c"]

        await item.delete(loaded)
        assert len(await item.query().all()) == 0
        if not is_mongo(db):
            assert await native_all(kind, db, "items_tags") == []
        else:
            assert (await native_all(kind, db, "items")) == []
    finally:
        await db.disconnect()
        _drop_mongo()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_one_to_one_tables_persist_load_and_cascade(kind):

    db = await connect_schema(kind, [Account, Profile, Post])
    try:
        account = db.repository(Account)
        profile = db.repository(Profile)
        await account.create(
            Account(id="a1", name="acme", profile=Profile(id="p1", bio="fast"))
        )

        await assert_created_tables(kind, db, {"accounts", "profiles"})

        prof = (await native_all(kind, db, "profiles"))[0]
        assert prof["bio"] == "fast"
        assert prof["account_id"] == "a1"

        acct = (await native_all(kind, db, "accounts"))[0]
        assert "profile" not in acct

        loaded = (await account.query().include(Account.profile).all())[0]
        assert loaded.profile.bio == "fast"

        await account.delete(loaded)
        assert len(await account.query().all()) == 0
        assert len(await profile.query().all()) == 0
        assert await native_all(kind, db, "profiles") == []
    finally:
        await db.disconnect()
        _drop_mongo()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_one_to_many_tables_persist_load_and_cascade(kind):

    db = await connect_schema(kind, [Account, Profile, Post])
    try:
        account = db.repository(Account)
        post = db.repository(Post)
        await account.create(
            Account(id="a1", name="acme", posts=[Post(id="p1", title="x"), Post(id="p2", title="y")])
        )

        await assert_created_tables(kind, db, {"accounts", "posts"})

        post_rows = await native_all(kind, db, "posts")
        assert sorted(r["title"] for r in post_rows) == ["x", "y"]
        assert all(r["account_id"] == "a1" for r in post_rows)

        loaded = (await account.query().include(Account.posts).all())[0]
        assert [p.title for p in loaded.posts] == ["x", "y"]

        await account.delete(loaded)
        assert len(await account.query().all()) == 0
        assert len(await post.query().all()) == 0
        assert await native_all(kind, db, "posts") == []
    finally:
        await db.disconnect()
        _drop_mongo()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_create_many_cascades_relationships(kind):
    db = await connect_schema(kind, [Account, Profile, Post])
    try:
        account = db.repository(Account)
        profile = db.repository(Profile)
        post = db.repository(Post)

        created = await account.create_many([
            Account(
                id="a1",
                name="acme",
                profile=Profile(id="p1", bio="fast"),
                posts=[Post(id="p1", title="x"), Post(id="p2", title="y")],
            ),
            Account(
                id="a2",
                name="globex",
                profile=Profile(id="p2", bio="steady"),
                posts=[Post(id="p3", title="z")],
            ),
        ])
        assert [a.id for a in created] == ["a1", "a2"]

        assert len(await account.query().all()) == 2

        profs = await native_all(kind, db, "profiles")
        assert sorted(r["bio"] for r in profs) == ["fast", "steady"]
        assert {r["account_id"] for r in profs} == {"a1", "a2"}

        post_rows = await native_all(kind, db, "posts")
        assert sorted(r["title"] for r in post_rows) == ["x", "y", "z"]
        assert sorted(r["account_id"] for r in post_rows) == ["a1", "a1", "a2"]

        loaded = {a.id: a for a in (await account.query().include(Account.posts).all())}
        assert [p.title for p in loaded["a1"].posts] == ["x", "y"]
        assert [p.title for p in loaded["a2"].posts] == ["z"]

        await account.delete_many()
        assert len(await post.query().all()) == 0
        assert len(await profile.query().all()) == 0
    finally:
        await db.disconnect()
        _drop_mongo()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_many_to_one_tables_persist_and_load(kind):
    db = await connect_schema(kind, [Employee, Department])
    try:
        employee = db.repository(Employee)
        department = db.repository(Department)
        await department.create(Department(id="d1", name="eng"))
        await employee.create(Employee(id="e1", name="bob", dept_id="d1"))

        await assert_created_tables(kind, db, {"employees", "departments"})

        emp_stored = (await native_all(kind, db, "employees"))[0]
        assert emp_stored["dept_id"] == "d1"
        dept_stored = (await native_all(kind, db, "departments"))[0]
        assert dept_stored["name"] == "eng"

        loaded = (await employee.query().include(Employee.dept).all())[0]
        assert loaded.dept.name == "eng"
    finally:
        await db.disconnect()
        _drop_mongo()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_many_to_many_metadata_and_owning_collections(kind):
    db = await connect_schema(kind, [Role])
    try:
        role = db.repository(Role)
        await role.create(Role(id="r1", name="admin"))

        meta = Employee.metadata()
        rel = meta.relationships["roles"]
        assert rel.kind == RelationshipKind.MANY_TO_MANY
        assert rel.through == "employee_roles"
        assert Role.metadata().table == "roles"

        await assert_created_tables(kind, db, {"roles"})
        role_stored = (await native_all(kind, db, "roles"))[0]
        assert role_stored["name"] == "admin"
    finally:
        await db.disconnect()
        _drop_mongo()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_reference_tables_and_fk_field(kind):
    db = await connect_schema(kind, [Employee, Department])
    try:
        employee = db.repository(Employee)
        department = db.repository(Department)
        await department.create(Department(id="d1", name="eng"))
        await employee.create(Employee(id="e1", name="bob", dept_id="d1"))

        meta = Employee.metadata()
        rel = meta.relationships["manager"]
        assert rel.kind == RelationshipKind.REFERENCE
        assert rel.foreign_key == "dept_id"

        await assert_created_tables(kind, db, {"employees", "departments"})

        emp_stored = (await native_all(kind, db, "employees"))[0]
        assert emp_stored["dept_id"] == "d1"

        rows = await employee.query().all()
        assert rows[0].dept_id == "d1"
        assert rows[0].manager is None
    finally:
        await db.disconnect()
        _drop_mongo()
