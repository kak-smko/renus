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
    Reference,
    RelationshipKind,
)

from tests.db import _native_helpers as nh

class MU_EOneAddr(ReModel):

    city: str
    code: str

class MU_EOneParent(ReModel):

    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    addr: MU_EOneAddr = Embedded(MU_EOneAddr)

class MU_EManyTag(ReModel):

    label: str

class MU_EManyParent(ReModel):

    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    tags: list[MU_EManyTag] = EmbeddedMany(MU_EManyTag)

class MU_OtoProfile(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    user_id: str = ""
    bio: str

class MU_OtoUser(ReModel):

    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    profile: MU_OtoProfile = OneToOne(
        MU_OtoProfile,
        foreign_key="user_id",
        cascade=("all",),
        on_delete="cascade",
        on_update="cascade",
        loading="selectin",
    )

class MU_OtmComment(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    post_id: str = ""
    text: str

class MU_OtmPost(ReModel):

    id: str = Field(database=DatabaseField(primary_key=True))
    title: str
    comments: list[MU_OtmComment] = OneToMany(
        MU_OtmComment,
        foreign_key="post_id",
        cascade=("all",),
        on_delete="cascade",
        on_update="cascade",
        loading="selectin",
    )

class MU_MtoDepartment(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

class MU_MtoEmployee(ReModel):

    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    dept_id: str = ""
    dept: MU_MtoDepartment = ManyToOne(
        MU_MtoDepartment, foreign_key="dept_id", loading="selectin"
    )

class MU_MtmRole(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

class MU_MtmUser(ReModel):

    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    roles: list[MU_MtmRole] = ManyToMany(MU_MtmRole, through="mu_mtm_user_roles")

class MU_RefDepartment(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

class MU_RefEmployee(ReModel):

    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    dept_id: str = ""
    manager: MU_RefDepartment = Reference(MU_RefDepartment, foreign_key="dept_id")

def _clean_value(v):
    if isinstance(v, dict):
        out = {}
        for k, val in v.items():
            out["id" if k == "_id" else k] = _clean_value(val)
        if out.get("id") is None:
            out.pop("id", None)
        return out
    if isinstance(v, list):
        return [_clean_value(x) for x in v]
    return v

def _degrease(rows: list[dict]) -> list[dict]:
    return [_clean_value(r) for r in rows]

async def _snapshot(db: object, tables: list[str]) -> dict[str, list[dict]]:
    return {t: _degrease(await nh.native_all(db, t)) for t in tables}

def _frozen(v):
    if isinstance(v, dict):
        return frozenset((k, _frozen(val)) for k, val in v.items())
    if isinstance(v, list):
        return tuple(_frozen(x) for x in v)
    return v

def _row_set(snap: dict[str, list[dict]], table: str, keys: set[str]):
    return {
        frozenset((k, _frozen(row[k])) for k in keys if k in row)
        for row in snap.get(table, [])
    }

def _expected_set(expected: list[dict]) -> set:
    keys = set(expected[0].keys())
    return {
        frozenset((k, _frozen(row[k])) for k in keys if k in row)
        for row in expected
    }

async def _assert_tables(kind: str, db: object, expected: set[str], label: str) -> None:
    created = set(await db.tables())
    missing = expected - created
    assert not missing, f"tables {label} missing: {missing} (created={created})"
    stray = created - expected
    assert not stray, f"tables {label} leaked: {stray} (created={created})"

def _assert_data(db: object, snap: dict[str, list[dict]], expected: dict[str, list[dict]]) -> None:
    for table, exp_rows in expected.items():
        if not exp_rows:
            assert snap.get(table, []) == [], f"{table} should be empty: {snap.get(table)}"
            continue
        keys = set(exp_rows[0].keys())
        got = _row_set(snap, table, keys)
        exp = _expected_set(exp_rows)
        assert got == exp, f"data mismatch in {table}: got {got} expected {exp}"

def _embedded_tables(kind: str, table: str, sub: str) -> set[str]:
    return {table} if kind == "mongodb" else {table, sub}

async def _capture_then_assert(
    kind: str,
    db: object,
    expected: dict[str, list[dict]],
    label: str,
) -> None:
    expected_tables = set(expected)
    await _assert_tables(kind, db, expected_tables, label)
    snap = await _snapshot(db, list(expected_tables))
    _assert_data(db, snap, expected)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_embedded_one_update_propagates_to_sub_table(kind):
    table, sub = "mu_eoneparents", "mu_eoneparents_addr"
    db = await nh.connect_schema(kind, [MU_EOneParent])
    try:
        repo = db.repository(MU_EOneParent)
        parent = await repo.create(
            MU_EOneParent(id="p1", name="acme", addr=MU_EOneAddr(city="tehran", code="10"))
        )
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after seed")

        rel = MU_EOneParent.metadata().relationships["addr"]
        assert rel.kind == RelationshipKind.EMBEDDED_ONE
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"
        assert rel.cascade == frozenset({"all"})

        parent.name = "acme-v2"
        await repo.save(parent)
        expected = {
            table: [{"id": "p1", "name": "acme-v2"}],
            sub: [{"parent_id": "p1", "city": "tehran", "code": "10"}],
        } if kind != "mongodb" else {
            table: [{"id": "p1", "name": "acme-v2", "addr": {"city": "tehran", "code": "10"}}],
        }
        await _capture_then_assert(kind, db, expected, "after scalar update")

        parent.name = "acme-v3"
        parent.addr.city = "qom"
        await repo.save(parent)
        expected = {
            table: [{"id": "p1", "name": "acme-v3"}],
            sub: [{"parent_id": "p1", "city": "qom", "code": "10"}],
        } if kind != "mongodb" else {
            table: [{"id": "p1", "name": "acme-v3", "addr": {"city": "qom", "code": "10"}}],
        }
        await _capture_then_assert(kind, db, expected, "after child edit")
        if kind != "mongodb":
            snap = await _snapshot(db, [sub])
            assert len(snap[sub]) == 1, f"stale embedded rows: {snap[sub]}"

        loaded = (await repo.query().include(MU_EOneParent.addr).all())[0]
        assert loaded.name == "acme-v3"
        assert loaded.addr.city == "qom"
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_embedded_many_update_replaces_sub_table(kind):
    table, sub = "mu_emanyparents", "mu_emanyparents_tags"
    db = await nh.connect_schema(kind, [MU_EManyParent])
    try:
        repo = db.repository(MU_EManyParent)
        parent = await repo.create(
            MU_EManyParent(
                id="p1",
                name="kit",
                tags=[MU_EManyTag(label="a"), MU_EManyTag(label="b")],
            )
        )
        await _assert_tables(kind, db, _embedded_tables(kind, table, sub), "after seed")

        rel = MU_EManyParent.metadata().relationships["tags"]
        assert rel.kind == RelationshipKind.EMBEDDED_MANY
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"
        assert rel.cascade == frozenset({"all"})

        parent.name = "kit-v2"
        await repo.save(parent)
        expected = {
            table: [{"id": "p1", "name": "kit-v2"}],
            sub: [{"parent_id": "p1", "label": "a"}, {"parent_id": "p1", "label": "b"}],
        } if kind != "mongodb" else {
            table: [{"id": "p1", "name": "kit-v2", "tags": [{"label": "a"}, {"label": "b"}]}],
        }
        await _capture_then_assert(kind, db, expected, "after scalar update")

        parent.name = "kit-v3"
        parent.tags = [MU_EManyTag(label="x")]
        await repo.save(parent)
        expected = {
            table: [{"id": "p1", "name": "kit-v3"}],
            sub: [{"parent_id": "p1", "label": "x"}],
        } if kind != "mongodb" else {
            table: [{"id": "p1", "name": "kit-v3", "tags": [{"label": "x"}]}],
        }
        await _capture_then_assert(kind, db, expected, "after collection replace")
        if kind != "mongodb":
            snap = await _snapshot(db, [sub])
            assert len(snap[sub]) == 1, f"stale embedded rows: {snap[sub]}"

        parent.name = "kit-v4"
        parent.tags = [MU_EManyTag(label="y"), MU_EManyTag(label="z")]
        await repo.save(parent)
        expected = {
            table: [{"id": "p1", "name": "kit-v4"}],
            sub: [{"parent_id": "p1", "label": "y"}, {"parent_id": "p1", "label": "z"}],
        } if kind != "mongodb" else {
            table: [{"id": "p1", "name": "kit-v4", "tags": [{"label": "y"}, {"label": "z"}]}],
        }
        await _capture_then_assert(kind, db, expected, "after collection grow")

        loaded = (await repo.query().include(MU_EManyParent.tags).all())[0]
        assert [t.label for t in loaded.tags] == ["y", "z"]
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_one_update_propagates_to_child_table(kind):
    db = await nh.connect_schema(kind, [MU_OtoUser, MU_OtoProfile])
    try:
        users = db.repository(MU_OtoUser)
        profiles = db.repository(MU_OtoProfile)
        user = await users.create(
            MU_OtoUser(id="u1", name="alice", profile=MU_OtoProfile(id="pf1", bio="fast"))
        )
        tables = ["mu_otousers", "mu_otoprofiles"]
        await _assert_tables(kind, db, set(tables), "after seed")

        rel = MU_OtoUser.metadata().relationships["profile"]
        assert rel.kind == RelationshipKind.ONE_TO_ONE
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"
        assert rel.cascade == frozenset({"all"})
        assert rel.loading == "selectin"

        user.name = "alice-smith"
        await users.save(user)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_otousers": [{"id": "u1", "name": "alice-smith"}],
                "mu_otoprofiles": [{"id": "pf1", "user_id": "u1", "bio": "fast"}],
            },
            "after scalar update",
        )

        user.name = "alice-smith-2"
        user.profile.bio = "steady"
        await users.save(user)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_otousers": [{"id": "u1", "name": "alice-smith-2"}],
                "mu_otoprofiles": [{"id": "pf1", "user_id": "u1", "bio": "steady"}],
            },
            "after child edit",
        )
        assert len(await profiles.query().all()) == 1, "duplicate OneToOne child"

        user.name = "alice-final"
        user.profile = MU_OtoProfile(id="pf2", bio="new")
        await users.save(user)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_otousers": [{"id": "u1", "name": "alice-final"}],

                "mu_otoprofiles": [
                    {"id": "pf1", "user_id": "u1", "bio": "steady"},
                    {"id": "pf2", "user_id": "u1", "bio": "new"},
                ],
            },
            "after child reassign",
        )

        loaded = (await users.query().include(MU_OtoUser.profile).all())[0]
        assert loaded.name == "alice-final"
        assert loaded.profile.bio == "new"
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_one_to_many_update_propagates_to_child_table(kind):
    db = await nh.connect_schema(kind, [MU_OtmPost, MU_OtmComment])
    try:
        posts = db.repository(MU_OtmPost)
        comments = db.repository(MU_OtmComment)
        post = await posts.create(
            MU_OtmPost(
                id="p1",
                title="hi",
                comments=[MU_OtmComment(id="c1", text="first")],
            )
        )
        tables = ["mu_otmposts", "mu_otmcomments"]
        await _assert_tables(kind, db, set(tables), "after seed")

        rel = MU_OtmPost.metadata().relationships["comments"]
        assert rel.kind == RelationshipKind.ONE_TO_MANY
        assert rel.on_delete == "cascade"
        assert rel.on_update == "cascade"
        assert rel.cascade == frozenset({"all"})
        assert rel.loading == "selectin"

        post.title = "hi-v2"
        await posts.save(post)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_otmposts": [{"id": "p1", "title": "hi-v2"}],
                "mu_otmcomments": [{"id": "c1", "post_id": "p1", "text": "first"}],
            },
            "after scalar update",
        )

        post.title = "hi-v3"
        for c in post.comments:
            if c.id == "c1":
                c.text = "edited"
        await posts.save(post)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_otmposts": [{"id": "p1", "title": "hi-v3"}],
                "mu_otmcomments": [{"id": "c1", "post_id": "p1", "text": "edited"}],
            },
            "after child edit",
        )

        post.title = "hi-v4"
        post.comments.append(MU_OtmComment(id="c2", text="second"))
        await posts.save(post)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_otmposts": [{"id": "p1", "title": "hi-v4"}],
                "mu_otmcomments": [
                    {"id": "c1", "post_id": "p1", "text": "edited"},
                    {"id": "c2", "post_id": "p1", "text": "second"},
                ],
            },
            "after child append",
        )

        loaded = (await posts.query().include(MU_OtmPost.comments).all())[0]
        assert [c.text for c in loaded.comments] == ["edited", "second"]
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_many_to_one_update_changes_fk_only(kind):
    db = await nh.connect_schema(kind, [MU_MtoEmployee, MU_MtoDepartment])
    try:
        employees = db.repository(MU_MtoEmployee)
        departments = db.repository(MU_MtoDepartment)
        await departments.create(MU_MtoDepartment(id="d1", name="eng"))
        await departments.create(MU_MtoDepartment(id="d2", name="ops"))
        emp = await employees.create(MU_MtoEmployee(id="e1", name="bob", dept_id="d1"))
        tables = ["mu_mtoemployees", "mu_mtodepartments"]
        await _assert_tables(kind, db, set(tables), "after seed")

        rel = MU_MtoEmployee.metadata().relationships["dept"]
        assert rel.kind == RelationshipKind.MANY_TO_ONE
        assert rel.foreign_key == "dept_id"
        assert rel.on_delete == "restrict"
        assert rel.loading == "selectin"

        emp.name = "bob-v2"
        emp.dept_id = "d2"
        await employees.save(emp)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_mtoemployees": [{"id": "e1", "name": "bob-v2", "dept_id": "d2"}],
                "mu_mtodepartments": [
                    {"id": "d1", "name": "eng"},
                    {"id": "d2", "name": "ops"},
                ],
            },
            "after fk repoint",
        )

        loaded = (await employees.query().include(MU_MtoEmployee.dept).all())[0]
        assert loaded.dept.name == "ops"
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_many_to_many_update_preserves_no_junction(kind):
    db = await nh.connect_schema(kind, [MU_MtmUser, MU_MtmRole])
    try:
        users = db.repository(MU_MtmUser)
        roles = db.repository(MU_MtmRole)
        await roles.create(MU_MtmRole(id="r1", name="admin"))
        await roles.create(MU_MtmRole(id="r2", name="editor"))
        user = await users.create(MU_MtmUser(id="u1", name="alice"))
        tables = ["mu_mtmusers", "mu_mtmroles", "mu_mtm_user_roles"]
        await _assert_tables(kind, db, set(tables), "after seed")

        rel = MU_MtmUser.metadata().relationships["roles"]
        assert rel.kind == RelationshipKind.MANY_TO_MANY
        assert rel.through == "mu_mtm_user_roles"
        assert rel.on_delete == "restrict"

        user.name = "alice-smith"
        await users.save(user)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_mtmusers": [{"id": "u1", "name": "alice-smith"}],
                "mu_mtmroles": [
                    {"id": "r1", "name": "admin"},
                    {"id": "r2", "name": "editor"},
                ],
                "mu_mtm_user_roles": [],
            },
            "after self update",
        )


        assert await nh.native_all(db, "mu_mtm_user_roles") == []
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_reference_update_changes_fk_only(kind):
    db = await nh.connect_schema(kind, [MU_RefEmployee, MU_RefDepartment])
    try:
        employees = db.repository(MU_RefEmployee)
        departments = db.repository(MU_RefDepartment)
        await departments.create(MU_RefDepartment(id="d1", name="eng"))
        await departments.create(MU_RefDepartment(id="d2", name="ops"))
        emp = await employees.create(MU_RefEmployee(id="e1", name="bob", dept_id="d1"))
        tables = ["mu_refemployees", "mu_refdepartments"]
        await _assert_tables(kind, db, set(tables), "after seed")

        rel = MU_RefEmployee.metadata().relationships["manager"]
        assert rel.kind == RelationshipKind.REFERENCE
        assert rel.foreign_key == "dept_id"
        assert rel.on_delete == "restrict"

        emp.name = "bob-v2"
        emp.dept_id = "d2"
        await employees.save(emp)
        await _capture_then_assert(
            kind,
            db,
            {
                "mu_refemployees": [{"id": "e1", "name": "bob-v2", "dept_id": "d2"}],
                "mu_refdepartments": [
                    {"id": "d1", "name": "eng"},
                    {"id": "d2", "name": "ops"},
                ],
            },
            "after fk repoint",
        )

        rows = await employees.query().all()
        assert rows[0].dept_id == "d2"
        assert rows[0].manager is None
    finally:
        await nh.cleanup(db)
