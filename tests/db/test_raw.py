from __future__ import annotations

from typing import Any

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Field,
    Model,
    SQLiteAdapter,
)

from tests.db import _native_helpers as nh

class Worker(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str
    salary: float

def _read(adapter: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict]:
    return [dict(r) for r in adapter._sqlite_db.execute(sql, params).fetchall()]

@pytest.mark.asyncio
async def test_sqlite_native_read():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()

    rows = _read(adapter, "SELECT 100 AS number, ? AS word;", ("test",))
    assert len(rows) == 1
    assert rows[0]["number"] == 100
    assert rows[0]["word"] == "test"

    rows2 = _read(adapter, "SELECT ? + ? AS total;", (10, 20))
    assert rows2[0]["total"] == 30

    await db.disconnect()

@pytest.mark.asyncio
async def test_native_write_and_read_visible():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Worker])

    repo = db.repository(Worker)
    await repo.create(Worker(name="W1", salary=40000.0))
    await repo.create(Worker(name="W2", salary=80000.0))

    conn = adapter._sqlite_db
    conn.execute('UPDATE "workers" SET "salary" = "salary" + ? WHERE "salary" > ?;', (1, 50000))
    conn.commit()

    rows = _read(adapter, 'SELECT "salary" FROM "workers" WHERE "name" = ?;', ("W2",))
    assert len(rows) == 1
    assert rows[0]["salary"] == 80001.0

    await db.disconnect()

@pytest.mark.asyncio
async def test_native_ddl():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Worker])

    reader = _read(adapter, 'SELECT "salary" FROM "workers" ORDER BY 1;')
    assert reader == []

    conn = adapter._sqlite_db
    conn.execute('CREATE INDEX "idx_worker_salary" ON "workers" ("salary");')
    conn.commit()

    await db.disconnect()

class RawItem(Model):
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
