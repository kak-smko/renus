from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from renus.db import (
    Column,
    Database,
    DatabaseField,
    Field,
    MigrationChecksumError,
    MigrationContext,
    MigrationManager,
    ReModel,
    SQLiteAdapter,
    UnsupportedOperationError,
)
from renus.db.mongodb.adapter import MongoDBAdapter

from tests.db import _native_helpers as nh

class MigratedUser(ReModel):
    id: int = DatabaseField(primary_key=True, generated=True)
    username: str = DatabaseField(unique=True)
    email: str = DatabaseField(indexed=True)
    is_active: bool = True

    class Meta:
        table = "migrated_users"
        timestamps = True

def test_migration_manager_create_sequential_files(tmp_path: Path):
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    mm = MigrationManager(db, path=tmp_path / "migrations")

    p1 = mm.create("create users")
    assert p1.name == "0001_create_users.py"
    assert p1.exists()
    content1 = p1.read_text(encoding="utf-8")
    assert "async def upgrade(ctx: MigrationContext)" in content1
    assert "async def downgrade(ctx: MigrationContext)" in content1

    p2 = mm.create("add email to users")
    assert p2.name == "0002_add_email_to_users.py"
    assert p2.exists()

    p3 = mm.create("add-profile-table")
    assert p3.name == "0003_add_profile_table.py"
    assert p3.exists()

@pytest.mark.asyncio
async def test_migration_upgrade_and_status(tmp_path: Path):
    db_file = tmp_path / "test.db"
    adapter = SQLiteAdapter({"database": str(db_file)})
    db = Database(adapter)
    await db.connect()

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    (mig_dir / "0001_create_accounts.py").write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.create_table("accounts", [
        Column("id", "int", primary_key=True, generated=True),
        Column("name", "str", nullable=False),
        Column("balance", "float", default=0.0),
    ])

async def downgrade(ctx):
    await ctx.drop_table("accounts")
""",
        encoding="utf-8",
    )

    (mig_dir / "0002_add_email.py").write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.add_column("accounts", Column("email", "str", nullable=True))
    await ctx.create_index("accounts", ["email"], unique=True, name="idx_acc_email")

async def downgrade(ctx):
    await ctx.drop_index("accounts", "idx_acc_email")
    await ctx.drop_column("accounts", "email")
""",
        encoding="utf-8",
    )

    mm = MigrationManager(db, path=mig_dir)

    statuses = await mm.status()
    assert len(statuses) == 2
    assert not statuses[0].applied
    assert not statuses[1].applied

    applied = await mm.upgrade()
    assert len(applied) == 2
    assert applied == ["0001_create_accounts", "0002_add_email"]

    statuses = await mm.status()
    assert len(statuses) == 2
    assert statuses[0].applied
    assert statuses[1].applied
    assert statuses[0].applied_at is not None

    await adapter.raw_sql(
        "INSERT INTO accounts (name, balance, email) VALUES (?, ?, ?)",
        ("Savings", 1500.0, "savings@bank.com"),
    )
    accs = await adapter.raw_sql("SELECT * FROM accounts WHERE email = ?", ("savings@bank.com",))
    assert len(accs) == 1
    assert accs[0]["name"] == "Savings"
    assert accs[0]["balance"] == 1500.0

    applied_again = await mm.upgrade()
    assert applied_again == []

    await db.disconnect()

@pytest.mark.asyncio
async def test_model_driven_migration(tmp_path: Path):
    db_file = tmp_path / "model_test.db"
    adapter = SQLiteAdapter({"database": str(db_file)})
    db = Database(adapter)
    await db.connect()

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    (mig_dir / "0001_users_table.py").write_text(
        """from tests.db.test_migrations import MigratedUser

async def upgrade(ctx):
    await ctx.create_model_table(MigratedUser)

async def downgrade(ctx):
    await ctx.drop_table("migrated_users")
""",
        encoding="utf-8",
    )

    mm = MigrationManager(db, path=mig_dir)
    applied = await mm.upgrade()
    assert applied == ["0001_users_table"]

    users_repo = db.repository(MigratedUser)
    u1 = await users_repo.create(MigratedUser(username="alice", email="alice@test.com"))
    assert u1.id == 1
    assert u1.is_persisted

    found = await users_repo.query(MigratedUser.username == "alice").first()
    assert found is not None
    assert found.email == "alice@test.com"

    await db.disconnect()

@pytest.mark.asyncio
async def test_migration_downgrades(tmp_path: Path):
    db_file = tmp_path / "downgrade.db"
    adapter = SQLiteAdapter({"database": str(db_file)})
    db = Database(adapter)
    await db.connect()

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    for i in range(1, 4):
        (mig_dir / f"{i:04d}_step_{i}.py").write_text(
            f"""from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.create_table("t_{i}", [Column("id", "int", primary_key=True)])

async def downgrade(ctx):
    await ctx.drop_table("t_{i}")
""",
            encoding="utf-8",
        )

    mm = MigrationManager(db, path=mig_dir)
    await mm.upgrade()

    statuses = await mm.status()
    assert all(s.applied for s in statuses)

    reverted1 = await mm.downgrade(1)
    assert reverted1 == ["0003_step_3"]

    statuses = await mm.status()
    assert statuses[0].applied
    assert statuses[1].applied
    assert not statuses[2].applied

    reverted_rest = await mm.reset()
    assert reverted_rest == ["0002_step_2", "0001_step_1"]

    statuses = await mm.status()
    assert not any(s.applied for s in statuses)

    await db.disconnect()

@pytest.mark.asyncio
async def test_migration_checksum_tampering_detection(tmp_path: Path):
    db_file = tmp_path / "tamper.db"
    adapter = SQLiteAdapter({"database": str(db_file)})
    db = Database(adapter)
    await db.connect()

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    f1 = mig_dir / "0001_initial.py"
    f1.write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.create_table("safe_table", [Column("id", "int", primary_key=True)])

async def downgrade(ctx):
    await ctx.drop_table("safe_table")
""",
        encoding="utf-8",
    )

    mm = MigrationManager(db, path=mig_dir)
    await mm.upgrade()
    assert await mm.check() is True

    f1.write_text(
        """# TAMPERED FILE!
from renus.db.migrations import Column

async def upgrade(ctx):
    pass

async def downgrade(ctx):
    pass
""",
        encoding="utf-8",
    )

    with pytest.raises(MigrationChecksumError):
        await mm.check()

    with pytest.raises(MigrationChecksumError):
        await mm.upgrade()

    await db.disconnect()

@pytest.mark.asyncio
async def test_migration_transactional_rollback(tmp_path: Path):
    db_file = tmp_path / "tx_fail.db"
    adapter = SQLiteAdapter({"database": str(db_file)})
    db = Database(adapter)
    await db.connect()

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    (mig_dir / "0001_good.py").write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.create_table("good_table", [Column("id", "int", primary_key=True)])

async def downgrade(ctx):
    await ctx.drop_table("good_table")
""",
        encoding="utf-8",
    )

    (mig_dir / "0002_broken.py").write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.create_table("broken_table", [Column("id", "int", primary_key=True)])
    raise RuntimeError("Simulated migration failure mid-transaction!")

async def downgrade(ctx):
    await ctx.drop_table("broken_table")
""",
        encoding="utf-8",
    )

    mm = MigrationManager(db, path=mig_dir)

    with pytest.raises(RuntimeError, match="Simulated migration failure"):
        await mm.upgrade()

    statuses = await mm.status()
    assert statuses[0].applied
    assert not statuses[1].applied

    accs = await adapter.raw_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='good_table'")
    assert len(accs) == 1

    await db.disconnect()

@pytest.mark.asyncio
async def test_mongo_migration_capability_limitations():
    adapter = MongoDBAdapter("mongodb://localhost:27017/test_db")

    adapter._client = MagicMock()
    mock_coll = MagicMock()
    mock_coll.update_many = AsyncMock()
    mock_db = MagicMock()
    mock_db.__getitem__.return_value = mock_coll
    adapter._db = mock_db

    db = Database(adapter)
    ctx = MigrationContext(db, adapter=adapter)

    await ctx.add_column("users", Column("age", "int"))
    await ctx.drop_column("users", "age")
    await ctx.rename_column("users", "old_age", "new_age")

    with pytest.raises(UnsupportedOperationError, match="is not an SQL adapter"):
        await ctx.execute_sql("SELECT * FROM users")

@pytest.mark.asyncio
async def test_mongo_column_migrations():
    adapter = MongoDBAdapter("mongodb://localhost:27017/test_db")
    mock_coll = MagicMock()
    mock_db = MagicMock()
    mock_db.__getitem__.return_value = mock_coll
    adapter._db = mock_db
    adapter._client = MagicMock()

    db = Database(adapter)
    ctx = MigrationContext(db, adapter=adapter)

    mock_coll.update_many = AsyncMock()
    await ctx.add_column("customers", Column("tier", "str", default="standard"))
    mock_coll.update_many.assert_awaited_once_with({}, {"$set": {"tier": "standard"}})

    mock_coll.update_many = AsyncMock()
    await ctx.add_column("customers", Column("nick", "str"))
    mock_coll.update_many.assert_not_awaited()

    mock_coll.update_many = AsyncMock()
    await ctx.drop_column("customers", "old_field")
    mock_coll.update_many.assert_awaited_once_with({}, {"$unset": {"old_field": ""}})

    mock_coll.update_many = AsyncMock()
    await ctx.rename_column("customers", "old_name", "new_name")
    mock_coll.update_many.assert_awaited_once_with({}, {"$rename": {"old_name": "new_name"}})

@pytest.mark.asyncio
async def test_mongo_full_migration_lifecycle(tmp_path: Path):
    mig_dir = tmp_path / "mongo_migrations"
    mig_dir.mkdir()

    (mig_dir / "0001_create_customers.py").write_text(
        """async def upgrade(ctx):
    await ctx.create_table("customers", [])
    await ctx.create_index("customers", ["email"], unique=True)

async def downgrade(ctx):
    await ctx.drop_table("customers")
""",
        encoding="utf-8",
    )

    adapter = MongoDBAdapter("mongodb://localhost:27017/test_db")

    collections: dict[str, Any] = {}
    migration_docs: list[dict[str, Any]] = []

    class MockMongoCollection:
        def __init__(self, name: str):
            self.name = name
            self.indexes: list[Any] = []

        async def create_index(self, keys: Any, unique: bool = False, name: str | None = None):
            self.indexes.append((keys, unique, name))

        async def drop_index(self, name: str):
            pass

        async def insert_one(self, doc: dict[str, Any]):
            migration_docs.append(dict(doc))
            return MagicMock(inserted_id="mock_oid")

        async def delete_one(self, filt: dict[str, Any]):
            for i, d in enumerate(list(migration_docs)):
                if d.get("version") == filt.get("version"):
                    migration_docs.pop(i)
                    break

        def find(self, filt: Any):
            class MockCursor:
                def sort(self, field: Any, direction: Any):
                    return self

                async def to_list(self, length: int):
                    return list(migration_docs)

            return MockCursor()

        async def drop(self):
            collections.pop(self.name, None)

    class MockMongoDB:
        def __getitem__(self, name: str):
            if name not in collections:
                collections[name] = MockMongoCollection(name)
            return collections[name]

        async def create_collection(self, name: str):
            collections[name] = MockMongoCollection(name)

        async def drop_collection(self, name: str):
            collections.pop(name, None)

    mock_session = MagicMock()
    mock_session.start_transaction = AsyncMock()
    mock_session.commit_transaction = AsyncMock()
    mock_session.abort_transaction = AsyncMock()
    mock_session.end_session = AsyncMock()

    mock_client = MagicMock()
    mock_client.start_session = MagicMock(return_value=mock_session)

    adapter._db = MockMongoDB()
    adapter._client = mock_client

    db = Database(adapter)
    mm = MigrationManager(db, path=mig_dir)

    applied = await mm.upgrade()
    assert applied == ["0001_create_customers"]
    assert len(migration_docs) == 1
    assert migration_docs[0]["version"] == "0001_create_customers"
    assert "customers" in collections

    statuses = await mm.status()
    assert len(statuses) == 1
    assert statuses[0].applied is True

    reverted = await mm.downgrade(1)
    assert reverted == ["0001_create_customers"]
    assert len(migration_docs) == 0
    assert "customers" not in collections

@pytest.mark.asyncio
async def test_migration_cli_lifecycle(tmp_path: Path):
    db_file = tmp_path / "cli_test.db"
    adapter = SQLiteAdapter({"database": str(db_file)})
    db = Database(adapter)
    await db.connect()

    mig_dir = tmp_path / "migrations"
    mm = MigrationManager(db, path=mig_dir)

    created_1 = mm.create("create_items")
    created_2 = mm.create("add_item_name")
    assert created_1.name == "0001_create_items.py"
    assert created_2.name == "0002_add_item_name.py"
    assert mig_dir.exists()

    (mig_dir / "0001_create_items.py").write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.create_table("items", [Column("id", "int", primary_key=True)])

async def downgrade(ctx):
    await ctx.drop_table("items")
""",
        encoding="utf-8",
    )
    (mig_dir / "0002_add_item_name.py").write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.add_column("items", Column("name", "str", nullable=True))

async def downgrade(ctx):
    await ctx.drop_column("items", "name")
""",
        encoding="utf-8",
    )

    statuses = await mm.status()
    assert [s.version for s in statuses] == ["0001_create_items", "0002_add_item_name"]
    assert not any(s.applied for s in statuses)

    applied = await mm.upgrade()
    assert applied == ["0001_create_items", "0002_add_item_name"]

    assert await mm.check() is True

    statuses = await mm.status()
    assert all(s.applied for s in statuses)

    rows = await adapter.raw_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
    )
    assert rows

    (mig_dir / "0001_create_items.py").write_text(
        (mig_dir / "0001_create_items.py").read_text(encoding="utf-8") + "\n# tamper\n",
        encoding="utf-8",
    )
    with pytest.raises(MigrationChecksumError):
        await mm.check()

    (mig_dir / "0001_create_items.py").write_text(
        """from renus.db.migrations import Column

async def upgrade(ctx):
    await ctx.create_table("items", [Column("id", "int", primary_key=True)])

async def downgrade(ctx):
    await ctx.drop_table("items")
""",
        encoding="utf-8",
    )

    reverted = await mm.downgrade()
    assert reverted == ["0002_add_item_name"]
    statuses = await mm.status()
    assert statuses[0].applied and not statuses[1].applied

    reverted = await mm.downgrade("base")
    assert reverted == ["0001_create_items"]
    statuses = await mm.status()
    assert not any(s.applied for s in statuses)

    assert await mm.reset() == []

    await db.disconnect()

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_migration_schema_and_tracking(kind, tmp_path: Path):
    db = await nh.connect_schema(kind, [])
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()
        (mig_dir / "0001_users_table.py").write_text(
            """from tests.db.test_migrations import MigratedUser

async def upgrade(ctx):
    await ctx.create_model_table(MigratedUser)

async def downgrade(ctx):
    await ctx.drop_table("migrated_users")
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)
        assert await mm.upgrade() == ["0001_users_table"]

        if db.adapter("primary").name == "mongodb":

            adapter = db.adapter("primary")
            cursor = await adapter._db["migrated_users"].list_indexes()
            idx_names = [i["name"] for i in await cursor.to_list(length=None)]
            assert any("username" in n for n in idx_names)
            assert any("email" in n for n in idx_names)
        else:
            raw = db.adapter("primary").execute_raw

            cols = {c["name"] for c in await raw('PRAGMA table_info("migrated_users");')}
            assert {"id", "username", "email", "is_active", "created_at", "updated_at"} <= cols

            idx = await raw('PRAGMA index_list("migrated_users");')
            idx_names = [i["name"] for i in idx]
            assert any("username" in n for n in idx_names) and any(i["unique"] == 1 for i in idx)
            assert any("email" in n for n in idx_names)

        users_repo = db.repository(MigratedUser)
        await users_repo.create(
            MigratedUser(id=1, username="native_alice", email="native@test.com")
        )
        stored = await nh.native_all(db, "migrated_users")
        assert len(stored) == 1
        assert stored[0]["username"] == "native_alice"
        assert stored[0]["is_active"] in (1, True)

        tracking = await nh.native_all(db, "_db_migrations")
        assert len(tracking) == 1
        assert tracking[0]["name"] == "users_table"
        assert "checksum" in tracking[0]
    finally:
        await nh.cleanup(db)

class NativeUserRow(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    username: str
    is_active: bool = True

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_dual_backend_persistence(kind):
    db = await nh.connect_schema(kind, [NativeUserRow])
    try:
        repo = db.repository(NativeUserRow)
        await repo.create(NativeUserRow(id="u1", username="native_alice", is_active=True))

        rows = await nh.native_all(db, "nativeuserrows")
        assert len(rows) == 1
        assert rows[0]["username"] == "native_alice"
        assert rows[0]["is_active"] in (1, True)
    finally:
        await nh.cleanup(db)
