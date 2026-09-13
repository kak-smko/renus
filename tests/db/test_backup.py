from __future__ import annotations

import os

import pytest

from renus.db import Database, DatabaseField, Field, ReModel, SQLiteAdapter

from tests.db import _native_helpers as nh

class BackupProduct(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str = Field(database=DatabaseField())

async def seed(db: Database, count: int) -> str:
    repo = db.repository(BackupProduct)
    for i in range(count):
        await repo.create(BackupProduct(name=f"Product-{i}"))
    return BackupProduct.__db_metadata__.table

async def table_count(db: Database, table: str) -> int:
    rows = await db.execute_raw(f'SELECT COUNT(*) AS c FROM "{table}";')
    return int(rows[0]["c"])

@pytest.mark.asyncio
async def test_paginated_backup_writes_single_json_file(tmp_path):
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([BackupProduct])
    table = await seed(db, 250)

    path = str(tmp_path / "db")
    counts = await db.backup(path=path, tables=[table], page_size=60)
    assert counts == {table: 250}

    file_path = os.path.join(path, f"{table}.json")
    assert os.path.exists(file_path)
    assert os.path.getsize(file_path) > 0

    await db.disconnect()

@pytest.mark.asyncio
async def test_paginated_backup_all_tables_detected(tmp_path):
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([BackupProduct])
    table = await seed(db, 250)

    path = str(tmp_path / "db")
    counts = await db.backup(path=path, page_size=100)
    assert counts[table] == 250

    await db.disconnect()

@pytest.mark.asyncio
@pytest.mark.parametrize("page_size,chunk_size", [(5, 3), (17, 50), (60, 60), (1000, 1000)])
async def test_paginated_backup_restore_round_trip(tmp_path, page_size, chunk_size):
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([BackupProduct])
    table = await seed(db, 450)

    path = str(tmp_path / "db")
    backed = await db.backup(path=path, tables=[table], page_size=page_size)
    assert backed == {table: 450}

    assert await table_count(db, table) == 450
    await db.execute_raw(f'DELETE FROM "{table}";')
    assert await table_count(db, table) == 0

    restored = await db.restore(path=path, tables=[table], chunk_size=chunk_size)
    assert restored == {table: 450}
    assert await table_count(db, table) == 450

    await db.disconnect()

@pytest.mark.asyncio
async def test_paginated_restore_drop_existing(tmp_path):
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([BackupProduct])
    table = await seed(db, 100)

    path = str(tmp_path / "db")
    await db.backup(path=path, tables=[table], page_size=20)

    await seed(db, 7)
    assert await table_count(db, table) == 107

    restored = await db.restore(path=path, tables=[table], drop_existing=True, chunk_size=10)
    assert restored == {table: 100}
    assert await table_count(db, table) == 100

    await db.disconnect()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_row_content_preserved_across_backup_restore(kind, tmp_path):
    db = await nh.connect_schema(kind, [BackupProduct])
    try:

        repo = db.repository(BackupProduct)
        await repo.create_many(
            [BackupProduct(id=i, name=f"Native-{i}") for i in range(1, 21)]
        )

        table = BackupProduct.__db_metadata__.table
        path = str(tmp_path / "db")
        await db.backup(path=path, tables=[table], page_size=7)

        if db.adapter("primary").name == "mongodb":
            await db.adapter("primary")._db[table].delete_many({})
        else:
            await db.execute_raw(f'DELETE FROM "{table}";')
        assert await nh.native_all(db, table) == []

        await db.restore(path=path, tables=[table], chunk_size=4)
        restored = await nh.native_all(db, table)
        assert await nh.table_count(db, table) == 20
        assert sorted(
            (r["name"] for r in restored), key=lambda n: int(n.replace("Native-", ""))
        ) == [f"Native-{i}" for i in range(1, 21)]
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_seeded_rows_on_both_backends(kind):
    db = await nh.connect_schema(kind, [BackupProduct])
    try:

        repo = db.repository(BackupProduct)
        await repo.create_many(
            [
                BackupProduct(id=1, name="Native-1"),
                BackupProduct(id=2, name="Native-2"),
                BackupProduct(id=3, name="Native-3"),
            ]
        )

        table = BackupProduct.__db_metadata__.table
        rows = await nh.native_all(db, table)
        names = {r["name"] for r in rows}
        assert names == {"Native-1", "Native-2", "Native-3"}
        assert await nh.table_count(db, table) == 3
    finally:
        await nh.cleanup(db)
