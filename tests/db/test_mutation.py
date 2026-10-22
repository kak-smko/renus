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
    Model,
    Repository,
    SQLiteAdapter,
    Update,
    UpdateMany,
    ValidationError,
)
from renus.db.repository.normalize import normalize_values


class Member(Model):
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
    assert normalize_values(ast.values) == {"username": "bob", "points": 50}

def test_insert_from_model():
    repo = Repository(None, Member)
    member = Member(username="carol", email="carol@example.com", points=250)
    ast = repo.build_insert_ast(member)

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
    repo = Repository(None, Member)
    m1 = Member(username="m1", email="m1@x.com")
    m2 = Member(username="m2", email="m2@x.com")

    ast = repo.build_insert_many_ast([m1, m2])
    assert ast.source is Member
    assert len(ast.records) == 2
    assert ast.records[0]["username"] == "m1"
    assert ast.records[1]["username"] == "m2"

def test_insert_many_empty_raises():
    repo = Repository(None, Member)
    with pytest.raises(ValueError, match="at least one model instance"):
        repo.build_insert_many_ast([])

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
    repo = Repository(None, Member)
    member = Member(id=10, username="eve", email="eve@x.com", points=0)
    member._mark_persisted()

    member.points = 100
    member.role = "admin"

    ast = repo.build_update_ast(member)
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

@pytest.mark.asyncio
async def test_update_validates_supplied_fields():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()
    await adapter.create_schema([Member])
    repo = Repository(adapter, Member)
    member = await repo.create(
        Member(username="update-target", email="update@example.com", points=10)
    )

    rows_affected = await repo.update(Member.id == member.id, {Member.points: 25})
    assert rows_affected == 1
    updated = await repo.query(Member.id == member.id).first()
    assert updated is not None
    assert updated.points == 25

    with pytest.raises(ValidationError, match="'points' must be of type int"):
        await repo.update(Member.id == member.id, {"points": "twenty-five"})
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_update_many_validates_supplied_fields_and_rejects_unknown_fields():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()
    await adapter.create_schema([Member])
    repo=Repository(adapter,Member)
    with pytest.raises(ValidationError, match="'is_active' must be of type bool"):
        await repo.update_many({"is_active": 1})

    with pytest.raises(ValidationError, match="Unknown field 'missing'"):
        await repo.update_many({"missing": True})

def test_delete_basic():
    cond = Member.id == 99
    ast = Delete(Member, filters=(cond,))
    assert isinstance(ast, Delete)
    assert ast.filters == (cond,)

def test_delete_from_model():
    repo = Repository(None, Member)
    member = Member(id=15, username="frank", email="frank@x.com")
    member._mark_persisted()

    ast = repo.build_delete_ast(member)
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

