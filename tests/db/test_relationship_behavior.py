from __future__ import annotations

import pytest

from renus.db import (
    DatabaseField,
    Embedded,
    EmbeddedMany,
    Field,
    ManyToMany,
    ManyToOne,
    OneToMany,
    OneToOne,
    ReModel,
    RelationshipKind,
)

from tests.db import _native_helpers as nh

class EOneAddr(ReModel):

    city: str
    zip: str

class EOneParent(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: EOneAddr = Embedded(EOneAddr)

class EManyTag(ReModel):

    label: str

class EManyParent(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    tags: list[EManyTag] = EmbeddedMany(EManyTag)

class OTOProfile(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    user_id: str = ""
    bio: str

class OTOUser(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    profile: OTOProfile = OneToOne(
        OTOProfile, foreign_key="user_id", cascade=("all",), on_delete="cascade"
    )

class OTORestrictUser(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    profile: OTOProfile = OneToOne(
        OTOProfile, foreign_key="user_id", cascade=(), on_delete="restrict"
    )

class OTMComment(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    post_id: str = ""
    text: str

class OTMPost(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    title: str
    comments: list[OTMComment] = OneToMany(
        OTMComment, foreign_key="post_id", cascade=("all",), on_delete="cascade"
    )

class OTMRestrictPost(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    title: str
    comments: list[OTMComment] = OneToMany(
        OTMComment, foreign_key="post_id", cascade=(), on_delete="restrict"
    )

class MTODepartment(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

class MTOEmployee(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    dept_id: str = ""
    dept: MTODepartment = ManyToOne(MTODepartment, foreign_key="dept_id")

class MTMRole(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

class MTMUser(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    roles: list[MTMRole] = ManyToMany(MTMRole, through="m2m_user_roles")

def _degrease(rows: list[dict]) -> list[dict]:
    return sorted(
        ({k: v for k, v in r.items() if k != "_id"} for r in rows),
        key=lambda d: (len(str(d)), str(d)),
    )

def _subset(rows: list[dict], keys: set[str]) -> list[dict]:
    return [{k: v for k, v in r.items() if k in keys} for r in rows]

async def _assert_tables(kind: str, db: object, expected_tables: set[str], label: str) -> None:
    created = set(await db.tables())
    missing = set(expected_tables) - created
    assert not missing, f"tables {label} not created: {missing} (created={created})"
    stray = created - expected_tables
    assert not stray, f"leaked tables {label}: {stray}"

def _assert_data(db: object, snap: dict[str, list[dict]], table: str, expected: list[dict]) -> None:
    actual = snap[table]
    if not expected:
        assert actual == [], f"{table} should be empty, got: {actual}"
        return
    keys = set(expected[0].keys())
    assert _subset(actual, keys) == expected, (
        f"data mismatch in {table}: got {_subset(actual, keys)} != {expected}"
    )
    assert len(actual) == len(expected), (
        f"row-count mismatch in {table}: got {len(actual)}, expected {len(expected)}"
    )

async def _snapshot(db: object, tables: list[str]) -> dict[str, list[dict]]:
    return {t: _degrease(await nh.native_all(db, t)) for t in tables}

def _embedded_tables(kind: str, table: str, sub: str) -> set[str]:
    return {table} if kind == "mongodb" else {table, sub}

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_embedded_one_cascade_load_and_data(kind):
    db = await nh.connect_schema(kind, [EOneParent])
    try:
        table, sub = "eoneparents", "eoneparents_address"
        repo = db.repository(EOneParent)
        await repo.create(
            EOneParent(id="p1", name="acme", address=EOneAddr(city="tehran", zip="12345"))
        )
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after seed")

        loaded = await repo.query(EOneParent.address.city == "tehran").first()
        assert loaded.name == "acme"
        loaded = await repo.query(EOneParent.address.city == "fake").first()
        assert loaded == None
        loaded = (await repo.query().include(EOneParent.address).all())[0]
        assert loaded.address.city == "tehran"
        assert loaded.address.zip == "12345"

        rel = EOneParent.metadata().relationships["address"]
        assert rel.kind == RelationshipKind.EMBEDDED_ONE
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"

        baseline = await _snapshot(db, [table, sub])
        if kind != "mongodb":
            _assert_data(db, baseline, sub, [
                {"parent_id": "p1", "city": "tehran", "zip": "12345"}
            ])
        else:
            assert len(baseline[table]) == 1

        await repo.delete(loaded)
        after = await _snapshot(db, [table, sub])
        _assert_data(db, after, table, [])
        _assert_data(db, after, sub, [])
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_embedded_one_update_repersists_no_duplicates(kind):
    db = await nh.connect_schema(kind, [EOneParent])
    try:
        table, sub = "eoneparents", "eoneparents_address"
        repo = db.repository(EOneParent)
        parent = await repo.create(
            EOneParent(id="p1", name="acme", address=EOneAddr(city="tehran", zip="1"))
        )
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after seed")

        parent.name = "acme-v2"
        parent.address.city = "qom"
        await repo.save(parent)

        after = await _snapshot(db, [table, sub])
        _assert_data(db, after, table, [{"name": "acme-v2"}])
        if kind != "mongodb":
            assert len(after[sub]) == 1, after[sub]
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_embedded_many_cascade_load_and_data(kind):
    db = await nh.connect_schema(kind, [EManyParent])
    try:
        table, sub = "emanyparents", "emanyparents_tags"
        repo = db.repository(EManyParent)
        await repo.create(
            EManyParent(
                id="p1",
                name="kit",
                tags=[EManyTag(label="a"), EManyTag(label="b"), EManyTag(label="c")],
            )
        )
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after seed")

        loaded = (await repo.query().include(EManyParent.tags).all())[0]
        assert [t.label for t in loaded.tags] == ["a", "b", "c"]

        baseline = await _snapshot(db, [table, sub])
        if kind != "mongodb":
            assert sorted(r["label"] for r in baseline[sub]) == ["a", "b", "c"]
        else:
            assert len(baseline[table]) == 1

        rel = EManyParent.metadata().relationships["tags"]
        assert rel.kind == RelationshipKind.EMBEDDED_MANY
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"

        await repo.delete(loaded)
        after = await _snapshot(db, [table, sub])
        _assert_data(db, after, table, [])
        _assert_data(db, after, sub, [])
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_embedded_many_update_replaces_collection(kind):
    db = await nh.connect_schema(kind, [EManyParent])
    try:
        table, sub = "emanyparents", "emanyparents_tags"
        repo = db.repository(EManyParent)
        parent = await repo.create(
            EManyParent(id="p1", name="kit", tags=[EManyTag(label="a"), EManyTag(label="b")])
        )
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after seed")

        parent.name = "kit-v2"
        parent.tags = [EManyTag(label="x")]
        await repo.save(parent)

        after = await _snapshot(db, [table, sub])
        _assert_data(db, after, table, [{"name": "kit-v2"}])
        if kind != "mongodb":
            assert sorted(r["label"] for r in after[sub]) == ["x"], after[sub]
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_one_cascade_load_and_data(kind):
    db = await nh.connect_schema(kind, [OTOUser, OTOProfile])
    try:
        users = db.repository(OTOUser)
        profiles = db.repository(OTOProfile)
        await users.create(
            OTOUser(id="u1", name="alice", profile=OTOProfile(id="pf1", bio="fast"))
        )
        await _assert_tables(kind, db, {"otousers", "otoprofiles"}, "after seed")

        prof_rows = await nh.native_all(db, "otoprofiles")
        assert prof_rows[0]["bio"] == "fast"
        assert prof_rows[0]["user_id"] == "u1"

        user_rows = await nh.native_all(db, "otousers")
        assert "profile" not in user_rows[0]

        baseline = await _snapshot(db, ["otousers", "otoprofiles"])
        _assert_data(db, baseline, "otoprofiles", [{"bio": "fast", "user_id": "u1"}])

        loaded = (await users.query().include(OTOUser.profile).all())[0]
        assert loaded.profile.bio == "fast"
        assert loaded.profile.user_id == "u1"

        rel = OTOUser.metadata().relationships["profile"]
        assert rel.kind == RelationshipKind.ONE_TO_ONE
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"

        await users.delete(loaded)
        assert len(await users.query().all()) == 0
        assert len(await profiles.query().all()) == 0
        after = await _snapshot(db, ["otousers", "otoprofiles"])
        _assert_data(db, after, "otousers", [])
        _assert_data(db, after, "otoprofiles", [])
        await _assert_tables(kind, db, {"otousers", "otoprofiles"}, "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_one_on_delete_restrict_keeps_child(kind):
    db = await nh.connect_schema(kind, [OTORestrictUser, OTOProfile])
    try:
        users = db.repository(OTORestrictUser)
        profiles = db.repository(OTOProfile)

        await users.create(OTORestrictUser(id="u1", name="alice"))
        await profiles.create(OTOProfile(id="pf1", user_id="u1", bio="fast"))
        await _assert_tables(kind, db, {"otorestrictusers", "otoprofiles"}, "after seed")

        rel = OTORestrictUser.metadata().relationships["profile"]
        assert rel.on_delete == "restrict"

        await users.delete((await users.query().all())[0])
        assert len(await users.query().all()) == 0

        assert len(await profiles.query().all()) == 1
        await _assert_tables(kind, db, {"otorestrictusers", "otoprofiles"}, "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_one_update_repersists_child(kind):
    db = await nh.connect_schema(kind, [OTOUser, OTOProfile])
    try:
        users = db.repository(OTOUser)
        profiles = db.repository(OTOProfile)
        user = await users.create(
            OTOUser(id="u1", name="alice", profile=OTOProfile(id="pf1", bio="fast"))
        )
        await _assert_tables(kind, db, {"otousers", "otoprofiles"}, "after seed")

        user.name = "alice-smith"
        user.profile.bio = "steady"
        await users.save(user)

        stored = (await profiles.query().all())[0]
        assert stored.bio == "steady"
        assert len(await profiles.query().all()) == 1
        await _assert_tables(kind, db, {"otousers", "otoprofiles"}, "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_many_cascade_load_and_data(kind):
    db = await nh.connect_schema(kind, [OTMPost, OTMComment])
    try:
        posts = db.repository(OTMPost)
        comments = db.repository(OTMComment)
        await posts.create(
            OTMPost(
                id="p1",
                title="hi",
                comments=[
                    OTMComment(id="c1", text="first"),
                    OTMComment(id="c2", text="second"),
                ],
            )
        )
        await _assert_tables(kind, db, {"otmposts", "otmcomments"}, "after seed")

        comment_rows = await nh.native_all(db, "otmcomments")
        assert sorted(r["text"] for r in comment_rows) == ["first", "second"]
        assert all(r["post_id"] == "p1" for r in comment_rows)

        baseline = await _snapshot(db, ["otmposts", "otmcomments"])
        _assert_data(db, baseline, "otmcomments", [
            {"text": "first", "post_id": "p1"},
            {"text": "second", "post_id": "p1"},
        ])

        loaded = (await posts.query().include(OTMPost.comments).all())[0]
        assert [c.text for c in loaded.comments] == ["first", "second"]

        rel = OTMPost.metadata().relationships["comments"]
        assert rel.kind == RelationshipKind.ONE_TO_MANY
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"

        await posts.delete(loaded)
        assert len(await comments.query().all()) == 0
        after = await _snapshot(db, ["otmposts", "otmcomments"])
        _assert_data(db, after, "otmcomments", [])
        await _assert_tables(kind, db, {"otmposts", "otmcomments"}, "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_many_on_delete_restrict_keeps_children(kind):
    db = await nh.connect_schema(kind, [OTMRestrictPost, OTMComment])
    try:
        posts = db.repository(OTMRestrictPost)
        comments = db.repository(OTMComment)

        await posts.create(OTMRestrictPost(id="p1", title="hi"))
        await comments.create(OTMComment(id="c1", post_id="p1", text="first"))
        await _assert_tables(kind, db, {"otmrestrictposts", "otmcomments"}, "after seed")

        rel = OTMRestrictPost.metadata().relationships["comments"]
        assert rel.on_delete == "restrict"

        await posts.delete((await posts.query().all())[0])
        assert len(await posts.query().all()) == 0
        assert len(await comments.query().all()) == 1
        await _assert_tables(kind, db, {"otmrestrictposts", "otmcomments"}, "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_many_update_repersists_children(kind):
    db = await nh.connect_schema(kind, [OTMPost, OTMComment])
    try:
        posts = db.repository(OTMPost)
        comments = db.repository(OTMComment)
        post = await posts.create(
            OTMPost(
                id="p1",
                title="hi",
                comments=[OTMComment(id="c1", text="first")],
            )
        )
        await _assert_tables(kind, db, {"otmposts", "otmcomments"}, "after seed")

        post.title = "hi-v2"
        post.comments.append(OTMComment(id="c2", text="second"))
        await posts.save(post)

        stored = await comments.query().all()
        assert sorted(c.text for c in stored) == ["first", "second"]
        await _assert_tables(kind, db, {"otmposts", "otmcomments"}, "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_many_to_one_load_and_data(kind):
    db = await nh.connect_schema(kind, [MTOEmployee, MTODepartment])
    try:
        employees = db.repository(MTOEmployee)
        departments = db.repository(MTODepartment)

        await departments.create(MTODepartment(id="d1", name="eng"))
        await departments.create(MTODepartment(id="d2", name="ops"))
        await employees.create(MTOEmployee(id="e1", name="bob", dept_id="d1"))
        await employees.create(MTOEmployee(id="e2", name="eve", dept_id="d1"))
        await employees.create(MTOEmployee(id="e3", name="kim", dept_id="d2"))
        await _assert_tables(kind, db, {"mtoemployees", "mtodepartments"}, "after seed")

        emp_rows = await nh.native_all(db, "mtoemployees")
        assert sorted(r["dept_id"] for r in emp_rows) == ["d1", "d1", "d2"]

        baseline = await _snapshot(db, ["mtoemployees", "mtodepartments"])
        _assert_data(db, baseline, "mtoemployees", [
            {"dept_id": "d1"},
            {"dept_id": "d1"},
            {"dept_id": "d2"},
        ])

        loaded = {
            e.name: e
            for e in (await employees.query().include(MTOEmployee.dept).all())
        }
        assert loaded["bob"].dept.name == "eng"
        assert loaded["eve"].dept.name == "eng"
        assert loaded["kim"].dept.name == "ops"

        rel = MTOEmployee.metadata().relationships["dept"]
        assert rel.kind == RelationshipKind.MANY_TO_ONE
        assert rel.foreign_key == "dept_id"

        departments_repo = db.repository(MTODepartment)
        await departments_repo.delete((await departments_repo.query().all())[0])
        assert len(await employees.query().all()) == 3
        await _assert_tables(kind, db, {"mtoemployees", "mtodepartments"}, "after scenario")
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_many_to_many_metadata_and_data(kind):
    db = await nh.connect_schema(kind, [MTMUser, MTMRole])
    try:
        roles = db.repository(MTMRole)
        users = db.repository(MTMUser)

        await roles.create(MTMRole(id="r1", name="admin"))
        await roles.create(MTMRole(id="r2", name="editor"))
        await users.create(MTMUser(id="u1", name="alice"))
        await _assert_tables(kind, db, {"mtmusers", "mtmroles"}, "after seed")

        rel = MTMUser.metadata().relationships["roles"]
        assert rel.kind == RelationshipKind.MANY_TO_MANY
        assert rel.through == "m2m_user_roles"
        assert rel.on_delete == "restrict"

        role_rows = await nh.native_all(db, "mtmroles")
        assert {r["name"] for r in role_rows} == {"admin", "editor"}

        await users.delete((await users.query().all())[0])
        assert len(await roles.query().all()) == 2
        await _assert_tables(kind, db, {"mtmusers", "mtmroles"}, "after scenario")
    finally:
        await nh.cleanup(db)
