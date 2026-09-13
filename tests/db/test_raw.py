from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Field,
    ReModel,
    SQLiteAdapter,
)

from tests.db import _native_helpers as nh

class Worker(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str
    salary: float

@pytest.mark.asyncio
async def test_repository_portable_raw_api():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Worker])

    repo = db.repository(Worker)
    await repo.create(Worker(name="Sam", salary=75000.0))

    assert hasattr(repo, "raw")
    assert not hasattr(repo, "raw_sql")
    assert not hasattr(repo, "raw_mongo")
    assert not hasattr(repo, "execute_raw")

    rows = await repo.raw('SELECT * FROM "workers" WHERE "name" = ?;', ("Sam",))
    workers = [repo._hydrate(r) for r in rows]
    assert len(workers) == 1
    assert isinstance(workers[0], Worker)
    assert workers[0].name == "Sam"
    assert workers[0].salary == 75000.0
    assert workers[0].is_persisted is True

    await db.disconnect()

@pytest.mark.asyncio
async def test_raw_statement_exposes_execute_and_await():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()

    repo = db.repository(Worker)
    statement = repo.raw("SELECT 100 AS answer;")

    assert hasattr(statement, "execute")
    result = await statement.execute()
    assert result[0]["answer"] == 100

    await db.disconnect()

@pytest.mark.asyncio
async def test_sqlite_execute_raw_sql_read():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()

    rows = await adapter.execute_raw("SELECT 100 AS number, ? AS word;", ("test",))
    assert len(rows) == 1
    assert rows[0]["number"] == 100
    assert rows[0]["word"] == "test"

    rows2 = await adapter.execute_raw("SELECT ? + ? AS total;", (10, 20))
    assert rows2[0]["total"] == 30

    await adapter.disconnect()

@pytest.mark.asyncio
async def test_database_execute_raw_read():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()

    rows = await db.execute_raw("SELECT 42 AS answer;")
    assert len(rows) == 1
    assert rows[0]["answer"] == 42

    await db.disconnect()

@pytest.mark.asyncio
async def test_repository_raw_sql_mutation():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Worker])

    repo = db.repository(Worker)
    await repo.create(Worker(name="W1", salary=40000.0))
    await repo.create(Worker(name="W2", salary=80000.0))

    result = await repo.raw(
        'UPDATE "workers" SET "salary" = "salary" + ? WHERE "salary" > ?;',
        1,
        50000,
    )
    assert result.rows_affected == 1

    rows = await repo.raw('SELECT "salary" FROM "workers" WHERE "name" = ?;', "W2")
    assert len(rows) == 1
    assert rows[0]["salary"] == 80001.0

    await db.disconnect()

@pytest.mark.asyncio
async def test_database_execute_raw_write():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Worker])

    repo = db.repository(Worker)
    await repo.create(Worker(name="A", salary=5.0))
    await repo.create(Worker(name="B", salary=50.0))

    result = await db.execute_raw(
        'UPDATE "workers" SET "salary" = "salary" + ? WHERE "salary" > ?;',
        (1, 10),
        connection="primary",
    )
    assert result.rows_affected == 1

    await db.disconnect()

@pytest.mark.asyncio
async def test_repository_raw_ddl():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Worker])

    repo = db.repository(Worker)
    result = await repo.raw('CREATE INDEX "idx_worker_salary" ON "workers" ("salary");')
    assert result.rows_affected >= 0

    await db.disconnect()

class RawItem(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    salary: float = 0.0

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_orm_write_visible_raw_on_both_backends(kind):
    db = await nh.connect_schema(kind, [RawItem])
    try:
        repo = db.repository(RawItem)
        await repo.create(RawItem(id="r1", name="Zara", salary=99999.0))

        rows = await nh.native_all(db, "rawitems")
        assert len(rows) == 1
        assert rows[0]["name"] == "Zara"
        assert rows[0]["salary"] == 99999.0

    finally:
        await nh.cleanup(db)
