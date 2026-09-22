from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from renus.db import (
    Avg,
    Count,
    Database,
    DatabaseError,
    DatabaseField,
    DuplicateKeyError,
    Embedded,
    Field,
    EmbeddedMany,
    Max,
    Min,
    MongoDBAdapter,
    MutationResult,
    Path,
    Model,
    Repository,
    Sum,
    Delete,
    DeleteMany,
    Insert,
    InsertMany,
    Update,
    UpdateMany,
)
from renus.db.mongodb.adapter import MongoTransactionContext
from renus.db.mongodb.compiler import MongoCompiledQuery, MongoCompiler


class Location(Model):
    city: str
    country: str

class OrderItem(Model):
    name: str
    price: float
    qty: int

class AccountDoc(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(database=DatabaseField(unique=True))
    age: int
    active: bool = True
    profile: Location = Embedded(Location)
    items: list[OrderItem] = EmbeddedMany(OrderItem)

    class Meta:
        timestamps = True
        soft_delete = True

def test_mongo_compiler_comparisons_and_predicates():
    compiler = MongoCompiler()
    repo = Repository(MongoDBAdapter(), AccountDoc)

    q_ast = repo.query(AccountDoc.age >= 18).ast
    compiled = compiler.compile_query(q_ast)
    assert isinstance(compiled, MongoCompiledQuery)
    assert compiled.collection == "accountdocs"
    assert compiled.filter["age"] == {"$gte": 18}
    assert compiled.filter["deleted_at"] is None

    q_in = repo.query(AccountDoc.username.in_(["u1", "u2"])).ast
    compiled_in = compiler.compile_query(q_in)
    assert compiled_in.filter["username"] == {"$in": ["u1", "u2"]}

    q_like = repo.query(AccountDoc.username.like("Alice%")).ast
    compiled_like = compiler.compile_query(q_like)
    assert "$regex" in compiled_like.filter["username"]
    assert compiled_like.filter["username"]["$regex"] == "^Alice.*$"

    q_between = repo.query(AccountDoc.age.between(20, 30)).ast
    compiled_between = compiler.compile_query(q_between)
    assert compiled_between.filter["age"] == {"$gte": 20, "$lte": 30}

def test_mongo_compiler_logical_combinations():
    compiler = MongoCompiler()
    repo = Repository(MongoDBAdapter(), AccountDoc)

    c1 = AccountDoc.age >= 18
    c2 = AccountDoc.active == True

    q_and = repo.query(c1 & c2).ast
    compiled_and = compiler.compile_query(q_and)
    assert "$and" in compiled_and.filter

    q_or = repo.query(c1 | c2).with_deleted().ast
    compiled_or = compiler.compile_query(q_or)
    assert "$or" in compiled_or.filter

    q_not = repo.query(~c1).with_deleted().ast
    compiled_not = compiler.compile_query(q_not)
    assert "$nor" in compiled_not.filter

def test_mongo_compiler_nested_paths_and_elemmatch():
    compiler = MongoCompiler()
    repo = Repository(MongoDBAdapter(), AccountDoc)

    q_nested = repo.query(AccountDoc.profile.city == "Tokyo").ast
    compiled_nested = compiler.compile_query(q_nested)
    assert compiled_nested.filter["profile.city"] == "Tokyo"

    q_elem = repo.query(AccountDoc.items.any(OrderItem.qty >= 5)).ast
    compiled_elem = compiler.compile_query(q_elem)
    assert "items" in compiled_elem.filter
    assert compiled_elem.filter["items"]["$elemMatch"]["qty"] == {"$gte": 5}

def test_mongo_compiler_sorting_projection_pagination():
    compiler = MongoCompiler()
    repo = Repository(MongoDBAdapter(), AccountDoc)

    q_ast = (
        repo.query(AccountDoc.active == True)
        .select(AccountDoc.id, AccountDoc.username)
        .order_by(AccountDoc.username.asc(), AccountDoc.age.desc())
        .limit(10)
        .offset(20)
        .ast
    )

    compiled = compiler.compile_query(q_ast)
    assert compiled.projection == {"_id": 1, "username": 1}
    assert compiled.sort == [("username", 1), ("age", -1)]
    assert compiled.limit == 10
    assert compiled.skip == 20

def test_mongo_compiler_aggregation_pipeline():
    compiler = MongoCompiler()
    repo = Repository(MongoDBAdapter(), AccountDoc)

    q_ast = (
        repo.query(AccountDoc.active == True)
        .group_by(AccountDoc.profile.country)
        .aggregate(
            total_users=Count(AccountDoc.id),
            avg_age=Avg(AccountDoc.age),
            max_age=Max(AccountDoc.age),
        )
        .ast
    )

    compiled = compiler.compile_query(q_ast)
    assert compiled.pipeline is not None
    assert len(compiled.pipeline) == 3

    match_stage = compiled.pipeline[0]
    assert "$match" in match_stage

    group_stage = compiled.pipeline[1]["$group"]
    assert group_stage["total_users"] == {"$sum": 1}
    assert group_stage["avg_age"] == {"$avg": "$age"}
    assert group_stage["max_age"] == {"$max": "$age"}

    project_stage = compiled.pipeline[2]["$project"]
    assert project_stage["profile.country"] == "$_id"
    assert project_stage["total_users"] == 1

def test_mongo_compiler_mutations():
    compiler = MongoCompiler()

    ins = Insert(AccountDoc, values={"id": 1, "username": "alice", "age": 25})
    coll, op, doc, extra = compiler.compile_mutation(ins)
    assert coll == "accountdocs"
    assert op == "insert_one"
    assert doc["_id"] == 1
    assert doc["username"] == "alice"

    ins_many = InsertMany(AccountDoc, records=[{"id": 1}, {"id": 2}])
    coll, op, payload, _ = compiler.compile_mutation(ins_many)
    assert op == "insert_many"
    assert len(payload["docs"]) == 2
    assert payload["docs"][0]["_id"] == 1

    upd = Update(AccountDoc, values={"age": 26}, filters=(AccountDoc.id == 1,))
    coll, op, filt, updates = compiler.compile_mutation(upd)
    assert op == "update_one"
    assert filt["_id"] == 1
    assert updates["$set"]["age"] == 26

    upd_many = UpdateMany(AccountDoc, values={"active": False}, filters=(AccountDoc.age < 18,))
    coll, op, filt, updates = compiler.compile_mutation(upd_many)
    assert op == "update_many"
    assert filt["age"] == {"$lt": 18}

    embedded_update = Update(
        AccountDoc,
        values={
            "items": [{"name": "book", "price": 12.5, "qty": 2}],
        },
        filters=(AccountDoc.id == 1,),
    )
    _, op, _, updates = compiler.compile_mutation(embedded_update)
    assert op == "update_one"
    assert updates["$set"]["items"] == [
        {"id": None, "name": "book", "price": 12.5, "qty": 2}
    ]

    del_ast = Delete(AccountDoc, filters=(AccountDoc.id == 1,))
    coll, op, filt, _ = compiler.compile_mutation(del_ast)
    assert op == "delete_one"
    assert filt["_id"] == 1

    del_many = DeleteMany(AccountDoc, filters=(AccountDoc.active == False,))
    coll, op, filt, _ = compiler.compile_mutation(del_many)
    assert op == "delete_many"
    assert filt["active"] is False


def test_mongodb_adapter_capabilities():
    adapter = MongoDBAdapter()
    assert adapter.name == "mongodb"
    assert adapter.nested_documents is True

def test_mongodb_adapter_connection_defaults():
    from renus.db.mongodb.adapter import (
        CONNECT_RETRIES,
        DEFAULT_CONNECT_TIMEOUT_MS,
        DEFAULT_MAX_POOL,
        DEFAULT_MIN_POOL,
        DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
    )

    adapter = MongoDBAdapter()

    assert DEFAULT_MAX_POOL >= 50
    assert DEFAULT_MIN_POOL >= 5
    assert DEFAULT_MIN_POOL <= DEFAULT_MAX_POOL
    assert DEFAULT_SERVER_SELECTION_TIMEOUT_MS >= 10_000
    assert CONNECT_RETRIES >= 1

    cfg = {
        "uri": "mongodb://localhost:27017",
        "database": "my_db",
        "max_pool": 200,
        "min_pool": 20,
    }
    assert cfg.get("max_pool", DEFAULT_MAX_POOL) == 200
    assert cfg.get("min_pool", DEFAULT_MIN_POOL) == 20
    assert cfg.get("server_selection_timeout_ms", DEFAULT_SERVER_SELECTION_TIMEOUT_MS) is not None
    assert cfg.get("connect_timeout_ms", DEFAULT_CONNECT_TIMEOUT_MS) is not None

@pytest.mark.asyncio
async def test_mongodb_mock_execution():
    adapter = MongoDBAdapter()

    mock_cursor = MagicMock()
    mock_cursor.sort = MagicMock(return_value=mock_cursor)
    mock_cursor.skip = MagicMock(return_value=mock_cursor)
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=[{"_id": 1, "username": "alice", "age": 25}])

    mock_coll = MagicMock()
    mock_coll.find = MagicMock(return_value=mock_cursor)
    mock_coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id=1))
    mock_coll.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock_coll.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    mock_coll.create_index = AsyncMock()

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_coll)
    mock_db.command = AsyncMock(return_value={"ok": 1})

    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    mock_client.close = MagicMock()

    adapter._mongo_client = mock_client
    adapter._mongo_db = mock_db

    assert await adapter.health_check() is True

    repo = Repository(adapter, AccountDoc)
    rows = await adapter.execute_query(repo.query(AccountDoc.username == "alice").ast)
    assert len(rows) == 1

    assert rows[0]["id"] == 1
    assert rows[0]["username"] == "alice"

    res = await adapter.execute_mutation(Insert(AccountDoc, values={"username": "alice", "age": 25}))
    assert isinstance(res, MutationResult)
    assert res.rows_affected == 1
    assert res.last_id == 1

    raw_res = await adapter._mongo_db.command({"ping": 1})
    assert raw_res == {"ok": 1}

    await adapter.disconnect()
    assert adapter._mongo_client is None

@pytest.mark.asyncio
async def test_mongodb_transaction_context():
    mock_session = MagicMock()
    mock_session.start_transaction = AsyncMock()
    mock_session.commit_transaction = AsyncMock()
    mock_session.abort_transaction = AsyncMock()
    mock_session.end_session = AsyncMock()

    ctx = MongoTransactionContext(mock_session)

    async with ctx:
        await ctx.commit()

    mock_session.start_transaction.assert_called_once()
    mock_session.commit_transaction.assert_called_once()
    mock_session.end_session.assert_called_once()

    mock_session.reset_mock()
    ctx2 = MongoTransactionContext(mock_session)

    with pytest.raises(RuntimeError):
        async with ctx2:
            raise RuntimeError("mongo tx error")

    mock_session.abort_transaction.assert_called_once()
    mock_session.end_session.assert_called_once()
