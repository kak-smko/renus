from __future__ import annotations

import os
import uuid

import pytest

from renus.db import (
    Database,
    DatabaseField,
    EmbeddedMany,
    Field,
    MongoDBAdapter,
    MySQLAdapter,
    ReModel,
    SQLiteAdapter,
)

from tests.db import _native_helpers as nh

class DocCountry(ReModel):
    name: str
    code: int

class DocTrans(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    key: str
    trans: dict
    tags: list
    countries: list[DocCountry] = EmbeddedMany(DocCountry)

MONGO_URI = "mongodb://localhost:27017"
_MONGO_DB = f"renus_raw_{os.getpid()}_{uuid.uuid4().hex[:6]}"
_MYSQL_DB = f"renus_raw_{os.getpid()}_{uuid.uuid4().hex[:6]}"

def _mysql_ready() -> bool:
    try:
        import aiomysql

        async def _probe() -> bool:
            try:
                pool = await aiomysql.create_pool(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="",
                    connect_timeout=2,
                    minsize=1,
                    maxsize=1,
                )
                pool.close()
                await pool.wait_closed()
                return True
            except Exception:
                return False

        import asyncio

        return asyncio.run(_probe())
    except Exception:
        return False

BACKENDS = [
    "sqlite",
    pytest.param(
        "mongodb",
        marks=pytest.mark.skipif(not nh.mongo_ready(), reason="MongoDB not reachable"),
    ),
    pytest.param(
        "mysql",
        marks=pytest.mark.skipif(not _mysql_ready(), reason="MySQL not reachable"),
    ),
]

def make_adapter(kind: str):
    if kind == "sqlite":
        return SQLiteAdapter({"database": ":memory:"})
    if kind == "mongodb":
        return MongoDBAdapter({"uri": MONGO_URI, "database": _MONGO_DB})
    return MySQLAdapter(
        {
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": _MYSQL_DB,
        }
    )

async def connect_schema(kind: str, models: list[type]) -> Database:
    db = Database(make_adapter(kind))
    await db.connect()
    await db.create_schema(models)
    return db

async def cleanup(db: Database) -> None:
    await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_bare_dict_list_auto_become_embedded(kind):
    db = await connect_schema(kind, [DocTrans])
    try:
        meta = DocTrans.metadata()
        assert "trans" not in meta.fields
        assert "tags" not in meta.fields
        assert meta.relationships["trans"].kind.value == "embedded_one"
        assert meta.relationships["trans"].is_embedded
        assert meta.relationships["tags"].kind.value == "embedded_many"
        assert meta.relationships["tags"].is_embedded
        assert meta.relationships["tags"].is_collection
    finally:
        await cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_dict_list_round_trip_and_subqueries(kind):
    db = await connect_schema(kind, [DocTrans])
    try:
        repo = db.repository(DocTrans)
        await repo.create(
            DocTrans(
                id="1",
                key="a",
                trans={"en": "one", "fa": "یک"},
                tags=["book", "pen", "3"],
                countries=[DocCountry(name="ir", code=10), DocCountry(name="us", code=1)],
            )
        )
        await repo.create(
            DocTrans(
                id="2",
                key="five",
                trans={"en": "5"},
                tags=["pen"],
                countries=[DocCountry(name="de", code=20)],
            )
        )

        objs = (
            await repo.query()
            .include(DocTrans.trans)
            .include(DocTrans.tags)
            .include(DocTrans.countries)
            .all()
        )
        by_id = {o.id: o for o in objs}

        assert by_id["1"].trans == {"en": "one", "fa": "یک"}
        assert by_id["1"].tags == ["book", "pen", "3"]
        assert [c.name for c in by_id["1"].countries] == ["ir", "us"]

        assert [o.id for o in await repo.query(DocTrans.trans.en == "one").all()] == ["1"]

        assert [o.id for o in await repo.query(DocTrans.tags.in_("book")).all()] == ["1"]

        assert sorted(o.id for o in await repo.query(DocTrans.tags.in_(["book", "z"])).all()) == ["1"]

        assert [o.id for o in await repo.query(DocTrans.tags == ["book", "pen"]).all()] == ["1"]

        assert [o.id for o in await repo.query(DocTrans.countries.name == "us").all()] == ["1"]
        assert [o.id for o in await repo.query(DocTrans.countries.code >= 10).all()] == ["1", "2"]
    finally:
        await cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", BACKENDS)
async def test_dict_list_reject_non_string_values(kind):

    db = await connect_schema(kind, [DocTrans])
    try:
        repo = db.repository(DocTrans)

        with pytest.raises(TypeError, match="must be strings"):
            await repo.create(
                DocTrans(id="1", key="a", trans={"en": 5}, tags=[], countries=[])
            )

        with pytest.raises(TypeError, match="must be strings"):
            await repo.create(
                DocTrans(id="2", key="a", trans={1: "v"}, tags=[], countries=[])
            )

        with pytest.raises(TypeError, match="must be strings"):
            await repo.create(
                DocTrans(id="3", key="a", trans={}, tags=["book", 3], countries=[])
            )
    finally:
        await cleanup(db)
