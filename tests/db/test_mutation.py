from __future__ import annotations

import pytest

from renus.db import (
    DatabaseField,
    Delete,
    Field,
    DeleteMany,
    FilterableMutation,
    Insert,
    InsertMany,
    MutationAST,
    Operator,
    ReModel,
    Update,
    UpdateMany,
    Upsert,
)
from renus.db.mutation.ast import (
    normalize_conflict_target,
    normalize_values,
)

from tests.db import _native_helpers as nh

class Member(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(database=DatabaseField(unique=True))
    email: str = Field(database=DatabaseField(unique=True))
    role: str = "user"
    points: int = 0
    is_active: bool = True

def test_insert_basic():
    ast = Insert(
        Member,
        values={"username": "alice", "email": "alice@example.com", "points": 100},
    )
    assert isinstance(ast, MutationAST)
    assert ast.source is Member
    assert ast.model_name == "Member"
    assert ast.values == {
        "username": "alice",
        "email": "alice@example.com",
        "points": 100,
    }

def test_insert_with_path_keys():

    ast = Insert(
        Member,
        values={Member.username: "bob", Member.points: 50},
    )
    assert ast.values == {"username": "bob", "points": 50}

def test_insert_from_model():
    member = Member(username="carol", email="carol@example.com", points=250)
    ast = Insert.from_model(member)

    assert ast.source is Member
    assert ast.values["username"] == "carol"
    assert ast.values["email"] == "carol@example.com"
    assert ast.values["points"] == 250

    assert "id" not in ast.values

def test_insert_many_basic():
    records = [
        {"username": "user1", "email": "u1@x.com"},
        {"username": "user2", "email": "u2@x.com"},
    ]
    ast = InsertMany(Member, records=records)
    assert isinstance(ast, MutationAST)
    assert ast.source is Member
    assert len(ast.records) == 2
    assert ast.records[0] == {"username": "user1", "email": "u1@x.com"}
    assert ast.records[1] == {"username": "user2", "email": "u2@x.com"}

def test_insert_many_from_models():
    m1 = Member(username="m1", email="m1@x.com")
    m2 = Member(username="m2", email="m2@x.com")

    ast = InsertMany.from_models([m1, m2])
    assert ast.source is Member
    assert len(ast.records) == 2
    assert ast.records[0]["username"] == "m1"
    assert ast.records[1]["username"] == "m2"

def test_insert_many_empty_raises():
    with pytest.raises(ValueError, match="at least one model instance"):
        InsertMany.from_models([])

def test_update_basic():
    cond = Member.id == 42
    ast = Update(Member, values={"points": 500}, filters=(cond,))
    assert isinstance(ast, FilterableMutation)
    assert ast.source is Member
    assert ast.values == {"points": 500}
    assert ast.filters == (cond,)

def test_update_where_chaining():
    ast1 = Update(Member, values={"points": 10}, filters=(Member.is_active == True,))
    ast2 = ast1.where(Member.role == "user")

    assert len(ast1.filters) == 1

    assert len(ast2.filters) == 2
    assert ast2.filters[0] == (Member.is_active == True)
    assert ast2.filters[1] == (Member.role == "user")

def test_update_from_model_with_dirty_tracking():
    member = Member(id=10, username="eve", email="eve@x.com", points=0)
    member._mark_persisted()

    member.points = 100
    member.role = "admin"

    ast = Update.from_model(member)
    assert ast.source is Member

    assert ast.values == {"points": 100, "role": "admin"}

    assert len(ast.filters) == 1
    assert ast.filters[0].operator == Operator.EQ
    assert ast.filters[0].path == Member.id
    assert ast.filters[0].value == 10

def test_update_many():
    cond = Member.role == "guest"

    ast = UpdateMany(
        Member,
        values={"is_active": False},
        filters=(cond,),
    )
    assert isinstance(ast, UpdateMany)
    assert ast.values == {"is_active": False}
    assert ast.filters == (cond,)

    chained = ast.where(Member.points == 0)
    assert len(chained.filters) == 2

def test_delete_basic():
    cond = Member.id == 99
    ast = Delete(Member, filters=(cond,))
    assert isinstance(ast, Delete)
    assert ast.filters == (cond,)

def test_delete_from_model():
    member = Member(id=15, username="frank", email="frank@x.com")
    member._mark_persisted()

    ast = Delete.from_model(member)
    assert ast.source is Member
    assert len(ast.filters) == 1
    assert ast.filters[0].operator == Operator.EQ
    assert ast.filters[0].path == Member.id
    assert ast.filters[0].value == 15

def test_delete_where_chaining():
    ast = Delete(Member, filters=(Member.id == 1,)).where(Member.role == "temp")
    assert len(ast.filters) == 2

def test_delete_many():
    cond = Member.is_active == False
    ast = DeleteMany(Member, filters=(cond,))
    assert isinstance(ast, DeleteMany)
    assert ast.filters == (cond,)

    chained = ast.where(Member.points == 0)
    assert len(chained.filters) == 2

def test_upsert_basic():
    ast = Upsert(
        Member,
        conflict_target=(Member.email,),
        create_values={"username": "grace", "email": "grace@x.com", "points": 10},
        update_values={"points": 20},
    )
    assert isinstance(ast, Upsert)
    assert ast.conflict_target == ("email",)
    assert ast.create_values == {
        "username": "grace",
        "email": "grace@x.com",
        "points": 10,
    }
    assert ast.update_values == {"points": 20}

def test_upsert_from_model():
    member = Member(id=101, username="heidi", email="heidi@x.com", points=50)

    ast = Upsert.from_model(member, conflict_target=(Member.email,))
    assert ast.conflict_target == ("email",)
    assert ast.create_values["username"] == "heidi"
    assert ast.create_values["email"] == "heidi@x.com"
    assert ast.create_values["id"] == 101

    assert "email" not in ast.update_values
    assert ast.update_values["username"] == "heidi"
    assert ast.update_values["points"] == 50

def test_upsert_from_model_default_pk():
    member = Member(id=102, username="ivan", email="ivan@x.com", points=75)

    ast = Upsert.from_model(member)
    assert ast.conflict_target == ("id",)
    assert "id" not in ast.update_values
    assert ast.update_values["username"] == "ivan"

def test_normalize_values():
    raw = {
        Member.username: "alice",
        "email": "a@x.com",
        "member.role": "admin",
    }
    norm = normalize_values(raw)
    assert norm == {
        "username": "alice",
        "email": "a@x.com",
        "role": "admin",
    }

def test_normalize_conflict_target():
    targets = [Member.username, "email", "member.id"]
    norm = normalize_conflict_target(targets)
    assert norm == ("username", "email", "id")

class NativeMember(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    username: str
    points: int = 0

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_mutation_ast_execution(kind):
    db = await nh.connect_schema(kind, [NativeMember])
    try:
        adapter = db.adapter("primary")

        await adapter.execute_mutation(
            Insert(NativeMember, values={"id": "m1", "username": "alice", "points": 10})
        )

        await adapter.execute_mutation(
            Update(NativeMember, values={"points": 99}, filters=(NativeMember.username == "alice",))
        )
        rows = await nh.native_all(db, "nativemembers")
        assert len(rows) == 1
        assert rows[0]["points"] == 99

        await adapter.execute_mutation(
            InsertMany(
                NativeMember,
                records=[{"id": "m2", "username": "b1"}, {"id": "m3", "username": "b2"}],
            )
        )
        assert await nh.table_count(db, "nativemembers") == 3

        await adapter.execute_mutation(Delete(NativeMember, filters=(NativeMember.username == "b1",)))
        remaining = await nh.native_all(db, "nativemembers")
        assert sorted(r["username"] for r in remaining) == ["alice", "b2"]
    finally:
        await nh.cleanup(db)
