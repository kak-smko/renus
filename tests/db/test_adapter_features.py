from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from renus.config import Config
from renus.db import (
    Column,
    Database,
    DatabaseField,
    DuplicateKeyError,
    Field,
    ID,
    Model,
)

from renus.db.sqlite import SQLiteAdapter
from tests.db._conformance import (
    adapter_for,
    cleanup,
    conformance_tests,
    database_for,
)


ADAPTERS = conformance_tests()


class FeatureRecord(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    email: str = Field(database=DatabaseField(unique=True))
    payload: str = ""


class EncodedRecord(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    when: datetime
    birthday: date
    at: time
    token: UUID
    identity: ID
    payload: dict
    blob: bytes


class DirectIndexRecord(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    email: str

    class Meta:
        table = "direct_indexes"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_direct_create_and_drop_table(kind):
    adapter = adapter_for(kind)
    try:
        await adapter.connect()
        await adapter.create_table(
            "direct_ddl",
            [
                Column("id", "str", primary_key=True),
                Column("email", "str", nullable=False),
            ],
        )
        assert "direct_ddl" in {name.lower() for name in await adapter.tables()}

        await adapter.drop_table("direct_ddl")
        assert "direct_ddl" not in {name.lower() for name in await adapter.tables()}
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_direct_create_and_drop_index(kind):
    adapter = adapter_for(kind)
    try:
        await adapter.connect()
        await adapter.create_table(
            "direct_indexes",
            [
                Column("id", "str", primary_key=True),
                Column("email", "str", nullable=False),
            ],
        )
        await adapter.create_index(
            "direct_indexes", ["email"], unique=True, name="idx_direct_email"
        )
        db = Database(adapter)
        repo = db.repository(DirectIndexRecord)
        await repo.create(DirectIndexRecord(id="one", email="same@example.com"))
        with pytest.raises(DuplicateKeyError):
            await repo.create(DirectIndexRecord(id="two", email="same@example.com"))

        await adapter.drop_index("direct_indexes", "idx_direct_email")
        await repo.create(DirectIndexRecord(id="two", email="same@example.com"))
        await adapter.drop_table("direct_indexes")
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_adapter_value_encoding_and_decoding(kind):
    previous_config = Config._cache.get("database")
    Config._cache["database"] = SimpleNamespace(ID=str)
    adapter = adapter_for(kind)
    await adapter.connect()
    try:
        meta = EncodedRecord.metadata()
        values = {
            "when": datetime(2026, 9, 19, 12, 30, 45, tzinfo=timezone.utc),
            "birthday": date(1990, 5, 20),
            "at": time(8, 15, 30),
            "token": UUID("12345678-1234-5678-1234-567812345678"),
            "identity": ID("record-1"),
            "payload": {"nested": [1, True, "value"]},
            "blob": b"renus-binary",
        }

        field_meta = {
            key: meta.fields[key]
            for key in values
            if key in meta.fields
        }
        field_meta["payload"] = SimpleNamespace(
            inferred_type=dict,
            column_name="payload",
        )
        encoded = {
            key: adapter.encode_value(value, field_meta[key])
            for key, value in values.items()
        }
        decoded = {
            key: adapter.decode_value(value, field_meta[key])
            for key, value in encoded.items()
        }
        assert decoded["when"] == values["when"]
        assert decoded["birthday"] == values["birthday"]
        assert decoded["at"] == values["at"]
        assert decoded["token"] == values["token"]
        assert decoded["identity"] == values["identity"]
        assert decoded["payload"] == values["payload"]
        assert decoded["blob"] == values["blob"]
    finally:
        await adapter.disconnect()
        if previous_config is None:
            Config._cache.pop("database", None)
        else:
            Config._cache["database"] = previous_config


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_after_connection_loss_reconnects(kind, tmp_path):
    if kind == "sqlite":
        adapter = SQLiteAdapter({"database": str(tmp_path / "reconnect.sqlite")})
        db = Database(adapter)
        await db.connect()
    else:
        db = await database_for(kind)
        adapter = db.adapter("primary")

    try:
        await db.create_schema([FeatureRecord])
        repo = db.repository(FeatureRecord)
        await repo.create(FeatureRecord(id="r1", email="one@example.com"))

        await adapter.disconnect()
        rows = await repo.where(FeatureRecord.id == "r1").all()
        assert [row.email for row in rows] == ["one@example.com"]
        assert await adapter.health_check() is True
    finally:
        await db.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_concurrent_upserts_leave_one_consistent_row(kind):
    db = await database_for(kind)
    try:
        await db.create_schema([FeatureRecord])
        repo = db.repository(FeatureRecord)

        async def write(value: str) -> None:
            await repo.upsert(
                conflict_target=("email",),
                create_values={
                    "id": "shared",
                    "email": "shared@example.com",
                    "payload": value,
                },
                update_values={"payload": value},
            )

        values = {f"writer-{index}" for index in range(8)}
        await asyncio.gather(*(write(value) for value in values))
        rows = await repo.where(FeatureRecord.email == "shared@example.com").all()
        assert len(rows) == 1
        assert rows[0].id == "shared"
        assert rows[0].payload in values
    finally:
        await cleanup(db)
