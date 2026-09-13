from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Field,
    ManyToMany,
    OneToMany,
    ReModel,
    RelationshipKind,
    SQLiteAdapter,
)

class User(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    role_id: str = ""

class Role(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    permission_id: str = ""

    users: list[User] = OneToMany(
        User,
        foreign_key="role_id",
        cascade=("all",),
        on_delete="cascade",
    )

class Permission(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

    roles: list[Role] = OneToMany(
        Role,
        foreign_key="permission_id",
        cascade=("all",),
        on_delete="cascade",
    )

class M2MRole(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    permissions: list["M2MPermission"] = ManyToMany(
        "M2MPermission", through="m2m_role_permissions"
    )

class M2MPermission(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str

class M2MUser(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    roles: list[M2MRole] = ManyToMany(M2MRole, through="m2m_user_roles")

async def _connect():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([User, Role, Permission])
    return db

async def _seed():
    db = await _connect()
    perms = db.repository(Permission)
    roles = db.repository(Role)
    users = db.repository(User)

    await perms.create(Permission(id="p1", name="manage_users"))
    await roles.create(Role(id="r1", name="admin", permission_id="p1"))
    await users.create(User(id="u1", name="alice", role_id="r1"))
    return db

def _first(repo, model, pk_value):
    return repo.query().where(model.id == pk_value).all()

@pytest.mark.asyncio
async def test_delete_role_leaves_permissions_unchanged():
    db = await _seed()
    try:
        perms = db.repository(Permission)
        roles = db.repository(Role)

        role = (await _first(roles, Role, "r1"))[0]
        await roles.delete(role)

        assert await roles.count(Role.id == "r1") == 0

        permissions = await perms.query().all()
        assert [p.id for p in permissions] == ["p1"]
        assert permissions[0].name == "manage_users"
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_update_role_leaves_permissions_unchanged():
    db = await _seed()
    try:
        perms = db.repository(Permission)
        roles = db.repository(Role)

        role = (await _first(roles, Role, "r1"))[0]
        role.name = "superuser"
        await roles.save(role)

        permissions = await perms.query().all()
        assert [p.id for p in permissions] == ["p1"]
        assert permissions[0].name == "manage_users"
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_delete_permission_cascades_to_roles():
    db = await _seed()
    try:
        perms = db.repository(Permission)
        roles = db.repository(Role)

        permission = (await _first(perms, Permission, "p1"))[0]
        await perms.delete(permission)

        assert await perms.count(Permission.id == "p1") == 0
        assert await roles.count(Role.id == "r1") == 0
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_delete_user_leaves_roles_unchanged():
    db = await _seed()
    try:
        roles = db.repository(Role)
        users = db.repository(User)

        user = (await _first(users, User, "u1"))[0]
        await users.delete(user)

        assert await users.count(User.id == "u1") == 0
        stored_roles = await roles.query().all()
        assert [r.id for r in stored_roles] == ["r1"]
        assert stored_roles[0].name == "admin"
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_update_user_leaves_roles_unchanged():
    db = await _seed()
    try:
        roles = db.repository(Role)
        users = db.repository(User)

        user = (await _first(users, User, "u1"))[0]
        user.name = "alice.smith"
        await users.save(user)

        stored_roles = await roles.query().all()
        assert [r.id for r in stored_roles] == ["r1"]
        assert stored_roles[0].name == "admin"
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_many_to_many_role_permission_metadata():
    rel = M2MRole.metadata().relationships["permissions"]
    assert rel.kind == RelationshipKind.MANY_TO_MANY
    assert rel.through == "m2m_role_permissions"

    assert M2MPermission.metadata().table == "m2mpermissions"

@pytest.mark.asyncio
async def test_many_to_many_user_role_metadata():
    rel = M2MUser.metadata().relationships["roles"]
    assert rel.kind == RelationshipKind.MANY_TO_MANY
    assert rel.through == "m2m_user_roles"
    assert M2MRole.metadata().table == "m2mroles"

@pytest.mark.asyncio
async def test_many_to_many_delete_role_does_not_delete_permissions():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    try:
        await db.create_schema([M2MUser, M2MRole, M2MPermission])
        perms = db.repository(M2MPermission)
        roles = db.repository(M2MRole)

        await perms.create(M2MPermission(id="p1", name="read"))
        await roles.create(M2MRole(id="r1", name="admin"))
        await roles.delete((await roles.query().all())[0])

        stored = await perms.query().all()
        assert [p.id for p in stored] == ["p1"]
        assert stored[0].name == "read"
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_many_to_many_delete_user_does_not_delete_roles():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    try:
        await db.create_schema([M2MUser, M2MRole, M2MPermission])
        users = db.repository(M2MUser)
        roles = db.repository(M2MRole)

        await roles.create(M2MRole(id="r1", name="admin"))
        await users.create(M2MUser(id="u1", name="alice"))
        await users.delete((await users.query().all())[0])

        stored = await roles.query().all()
        assert [r.id for r in stored] == ["r1"]
        assert stored[0].name == "admin"
    finally:
        await db.disconnect()

@pytest.mark.asyncio
async def test_delete_role_cascades_to_users():
    db = await _seed()
    try:
        roles = db.repository(Role)
        users = db.repository(User)

        role = (await _first(roles, Role, "r1"))[0]
        await roles.delete(role)

        assert await roles.count(Role.id == "r1") == 0
        assert await users.count(User.id == "u1") == 0
    finally:
        await db.disconnect()
