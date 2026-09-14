from __future__ import annotations

import inspect
import os
import uuid

import pytest

from renus.db import Database, MongoDBAdapter, SQLiteAdapter

MONGO_URI = "mongodb://localhost:27017"

def mongo_ready() -> bool:
    try:
        import pymongo

        client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False

def backends() -> list:
    return [
        "sqlite",
        pytest.param(
            "mongodb",
            marks=pytest.mark.skipif(not mongo_ready(), reason="MongoDB not reachable"),
        ),
    ]

DUAL_BACKENDS = backends()

def _unique_db() -> str:
    return f"renus_native_{os.getpid()}_{uuid.uuid4().hex[:8]}"

def make_adapter(kind: str):
    if kind == "sqlite":
        return SQLiteAdapter({"database": ":memory:"})
    return MongoDBAdapter({"uri": MONGO_URI, "database": _unique_db()})

async def connect_schema(kind: str, models: list[type]) -> Database:
    db = Database(make_adapter(kind))
    await db.connect()
    await db.create_schema(models)
    return db

async def native_all(db: Database, table: str) -> list[dict]:
    if db.adapter("primary").name == "mongodb":
        coll = db.adapter("primary")._mongo_db[table]
        return [dict(d) for d in await coll.find({}).to_list(length=None)]
    conn = db.adapter("primary")._sqlite_db
    return [dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1;').fetchall()]

async def table_count(db: Database, table: str) -> int:
    if db.adapter("primary").name == "mongodb":
        coll = db.adapter("primary")._mongo_db[table]
        return await coll.count_documents({})
    conn = db.adapter("primary")._sqlite_db
    row = conn.execute(f'SELECT COUNT(*) AS c FROM "{table}";').fetchone()
    return int(row[0])

async def created_tables(db: Database) -> set[str]:
    return set(await db.tables())

async def cleanup(db: Database) -> None:
    try:
        if db.adapter("primary").name == "mongodb":
            adapter = db.adapter("primary")
            drop = adapter._mongo_client.drop_database(adapter._mongo_db.name)
            if inspect.isawaitable(drop):
                await drop
        await db.disconnect()
    except Exception:
        pass
