from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from renus.db import (
    Avg,
    Count,
    Database,
    DatabaseField,

    Field,

    Max,
    Min,
    MongoDBAdapter,
    MutationResult,
    Model,
    OneToOne,
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

class TagDoc(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    tags: list

class OrderItem(Model):
    name: str
    price: float
    qty: int

class AccountDoc(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = Field(database=DatabaseField(unique=True))
    age: int
    active: bool = True
    profile: Location
    items: list[OrderItem]

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

def test_mongo_filter_rejects_operator_dicts_in_values():
    from renus.db import DatabaseError, Path

    compiler = MongoCompiler()
    repo = Repository(MongoDBAdapter(), AccountDoc)

    # A dict value must be treated as data, not re-interpreted as operators.
    q_ast = repo.query(Path(AccountDoc, ("age",)) == {"$ne": None}).ast
    with pytest.raises(DatabaseError):
        compiler.compile_query(q_ast)

def test_mongo_json_list_path_encodes_values():
    from renus.db import DatabaseError, Path

    compiler = MongoCompiler()
    repo = Repository(MongoDBAdapter(), TagDoc)

    # Values in a list field still pass through the normal value encoder.
    q_ast = repo.query(Path(TagDoc, ("tags",)) == [{"$ne": None}]).ast
    with pytest.raises(DatabaseError):
        compiler.compile_query(q_ast)

    q_ok = repo.query(Path(TagDoc, ("tags",)) == ["a", "b"]).ast
    compiled = compiler.compile_query(q_ok)
    assert compiled.filter["tags"] == ["a", "b"]

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
        { "name": "book", "price": 12.5, "qty": 2}
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

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "uri", "database", "expected_options"),
    [
        (
            {},
            "mongodb://localhost:27017",
            "db",
            {
                "maxPoolSize": 100,
                "minPoolSize": 10,
                "serverSelectionTimeoutMS": 30_000,
                "connectTimeoutMS": 2_000,
            },
        ),
        (
            {
                "uri": "mongodb://db.example:27018",
                "database": "my_db",
                "max_pool": "200",
                "min_pool": "20",
                "server_selection_timeout_ms": "12000",
                "connect_timeout_ms": "2500",
                "socket_timeout_ms": "7000",
                "username": "tester",
                "password": "secret",
                "retries": 1,
            },
            "mongodb://db.example:27018",
            "my_db",
            {
                "maxPoolSize": 200,
                "minPoolSize": 20,
                "serverSelectionTimeoutMS": 12_000,
                "connectTimeoutMS": 2_500,
                "socketTimeoutMS": 7_000,
                "username": "tester",
                "password": "secret",
            },
        ),
    ],
)
async def test_mongodb_adapter_connection_options(
    monkeypatch, config, uri, database, expected_options
):
    from renus.db.mongodb import adapter as mongodb_adapter_module
    from renus.db.mongodb.adapter import (
        CONNECT_RETRIES,
        DEFAULT_CONNECT_TIMEOUT_MS,
        DEFAULT_MAX_POOL,
        DEFAULT_MIN_POOL,
        DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
    )

    assert DEFAULT_MAX_POOL >= 50
    assert DEFAULT_MIN_POOL >= 5
    assert DEFAULT_MIN_POOL <= DEFAULT_MAX_POOL
    assert DEFAULT_SERVER_SELECTION_TIMEOUT_MS >= 10_000
    assert DEFAULT_CONNECT_TIMEOUT_MS >= 1
    assert CONNECT_RETRIES >= 1

    mock_db = MagicMock()
    mock_db.command = AsyncMock(return_value={"ok": 1})
    mock_client = MagicMock()
    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    mock_client.close = MagicMock()
    client_factory = MagicMock(return_value=mock_client)
    monkeypatch.setattr(mongodb_adapter_module, "AsyncMongoClient", client_factory)

    adapter = MongoDBAdapter(config)
    await adapter.connect()

    client_factory.assert_called_once_with(uri, **expected_options)
    mock_client.__getitem__.assert_called_once_with(database)
    mock_db.command.assert_awaited_once_with("ping")

    await adapter.disconnect()
    mock_client.close.assert_called_once_with()

@pytest.mark.asyncio
async def test_mongodb_update_with_unchanged_primary_key_keeps_other_changes():
    adapter = MongoDBAdapter()
    collection = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(
        return_value=[{"_id": "same", "name": "before"}]
    )
    collection.find = MagicMock(return_value=cursor)
    collection.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    database = MagicMock()
    database.__getitem__ = MagicMock(return_value=collection)
    adapter._mongo_db = database

    result = await adapter._run_mutation(
        "accounts",
        "update_one",
        {"_id": "same"},
        {"$set": {"_id": "same", "name": "after"}},
    )

    assert result.rows_affected == 1
    collection.update_one.assert_awaited_once_with(
        {"_id": "same"},
        {"$set": {"name": "after"}},
        session=None,
    )
    collection.insert_one.assert_not_called()


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
    query = repo.query(AccountDoc.username == "alice")
    compiled_query = adapter.compile_query(query.ast)
    rows = await adapter.execute_query(query.ast)
    assert len(rows) == 1

    assert rows[0]["id"] == 1
    assert rows[0]["username"] == "alice"
    mock_coll.find.assert_called_once_with(
        compiled_query.filter,
        projection=compiled_query.projection,
        session=None,
    )
    mock_cursor.to_list.assert_awaited_once_with(length=compiled_query.limit or 5000)

    insert = Insert(AccountDoc, values={"username": "alice", "age": 25})
    collection, operation, document, extra = adapter.compile_mutation(insert)
    res = await adapter.execute_mutation(insert)
    assert isinstance(res, MutationResult)
    assert res.rows_affected == 1
    assert res.last_id == 1
    assert collection == "accountdocs"
    assert operation == "insert_one"
    mock_db.__getitem__.assert_called_with(collection)
    mock_coll.insert_one.assert_awaited_once_with(document, session=None)

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

@pytest.mark.asyncio
async def test_mongodb_graph_delete_cascades_to_child():
    class GraphChilds(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        total_childs: int = 0

    class GraphScore(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        total: int = 0

    class Graph(Model):
        id: str = Field(
            database=DatabaseField(primary_key=True),
        )
        gen: str = Field(database=DatabaseField(unique=True, indexed=True))
        rank_id: int
        childs: GraphChilds = OneToOne(
            GraphChilds,
            local_key="gen",
            foreign_key="id",
            on_save="cascade",
            on_delete="cascade",
        )
        score: GraphScore = OneToOne(
            GraphScore,
            local_key="gen",
            foreign_key="id",
            on_save="cascade",
            on_delete="cascade",
        )

    database_name = f"renus_graph_delete_test_{uuid4().hex}"
    adapter = MongoDBAdapter(
        {
            "uri": "mongodb://localhost:27017",
            "database": database_name,
            "retries": 1,
            "server_selection_timeout_ms": 1000,
        }
    )
    db = Database(adapter)
    connected = False

    try:
        await db.connect()
        connected = True
    except Exception as exc:
        pytest.skip(f"MongoDB is unavailable: {exc}")

    try:
        hello = await adapter._mongo_db.command("hello")
        if not (hello.get("setName") or hello.get("msg") == "isdbgrid"):
            pytest.skip("MongoDB transactions require a replica set or sharded cluster")

        await db.create_schema([Graph, GraphChilds, GraphScore])
        graph_repo: Repository[Graph] = db.repository(Graph)
        child_repo: Repository[GraphChilds] = db.repository(GraphChilds)
        await graph_repo.create(
            Graph(
                id="123",
                gen="graph-1",
                rank_id=1,
                childs=GraphChilds(id="graph-1", total_childs=1),
                score=GraphScore(id="graph-1", total=10),
            )
        )

        assert await child_repo.count() == 1
        node= await graph_repo.where(Graph.id=="123").include(Graph.childs).include(Graph.score).first()
        assert node.childs.id == "graph-1"
        assert node.score.id == "graph-1"
        assert await graph_repo.delete_many(Graph.gen == "graph-1") == 1
        assert await graph_repo.count() == 0
        assert await child_repo.count() == 0
    finally:
        if connected:
            await adapter._mongo_client.drop_database(database_name)
        await db.disconnect()


@pytest.mark.asyncio
async def test_native_mongodb_graph_update():
    class GraphChilds(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        total_childs: int = 0

    class Graph(Model):
        id: int = Field(database=DatabaseField(primary_key=True, generated=True))
        parent: int = 0
        gen: str = Field(database=DatabaseField(unique=True, indexed=True))
        genum: str
        status: int = 0

    database_name = f"renus_graph_test_{uuid4().hex}"
    adapter = MongoDBAdapter(
        {
            "uri": "mongodb://localhost:27017",
            "database": database_name,
            "retries": 1,
            "server_selection_timeout_ms": 1000,
        }
    )
    db = Database(adapter)

    try:
        await db.connect()
    except Exception as exc:
        pytest.skip(f"MongoDB is unavailable: {exc}")

    try:
        hello = await adapter._mongo_db.command("hello")
        if not (hello.get("setName") or hello.get("msg") == "isdbgrid"):
            pytest.skip("MongoDB transactions require a replica set or sharded cluster")

        graph_repo: Repository[Graph] = db.repository(Graph)
        child_repo: Repository[GraphChilds] = db.repository(GraphChilds)
        await child_repo.create_many(
            [
                GraphChilds(id="0"),
                GraphChilds(id="a"),
                GraphChilds(id="b"),
                GraphChilds(id="c"),
                GraphChilds(id="d"),
            ]
        )
        await graph_repo.create_many(
            [
                Graph(id=0, gen="0", genum="-0-"),
                Graph(id=1, gen="a", genum="-0-a-"),
                Graph(id=2, gen="b", genum="-0-a-b-"),
                Graph(id=3, gen="c", genum="-0-a-b-c-"),
                Graph(id=4, gen="d", genum="-0-a-d-"),
            ]
        )

        nodes = (
            await graph_repo.where(Graph.status == 0)
            .select(Graph.genum, Graph.id)
            .limit(100)
            .all()
        )
        book: dict[str, int] = {}
        for node in nodes:
            ancestors = [part for part in node["genum"].split("-") if part][:-1]
            for ancestor in ancestors:
                book[ancestor] = book.get(ancestor, 0) + 1

        nodes_id = [node["id"] for node in nodes]
        async with db.transaction():
            await graph_repo.where(Graph.id.in_(nodes_id)).update({"status": 1})
            child_collection = adapter._mongo_db[GraphChilds.metadata().table]
            for ancestor, total in book.items():
                await child_collection.update_one(
                    {"_id": ancestor},
                    {"$inc": {"total_childs": total}},
                    session=adapter._tx_session,
                )

        graph_collection = adapter._mongo_db[Graph.metadata().table]
        assert await graph_collection.count_documents({"status": 1}) == 5
        assert (await child_collection.find_one({"_id": "0"}))[
            "total_childs"
        ] == 4
        assert (await child_collection.find_one({"_id": "a"}))[
            "total_childs"
        ] == 3
        assert (await child_collection.find_one({"_id": "b"}))[
            "total_childs"
        ] == 1
    finally:
        await adapter._mongo_client.drop_database(database_name)
        await db.disconnect()
