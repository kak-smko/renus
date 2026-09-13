from __future__ import annotations

import pytest

from renus.db import (
    Database,
    DatabaseCapabilities,
    DatabaseField,
    Field,
    ReModel,
    SQLiteAdapter,
    UnsupportedOperationError,
)

from tests.db import _native_helpers as nh

class BankAccount(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    owner: str
    balance: float = 0.0

class AuditLog(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    action: str

@pytest.mark.asyncio
async def test_uow_cross_repository_atomic_commit():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([BankAccount, AuditLog])

    account_repo = db.repository(BankAccount)
    audit_repo = db.repository(AuditLog)

    async with db.unit_of_work() as uow:
        acc_uow = uow.repository(BankAccount)
        audit_uow = uow.repository(AuditLog)

        await acc_uow.create(BankAccount(owner="Alice", balance=1000.0))
        await audit_uow.create(AuditLog(action="Account created for Alice"))
        await uow.commit()

    assert await account_repo.count() == 1
    assert await audit_repo.count() == 1

    await db.disconnect()

@pytest.mark.asyncio
async def test_uow_cross_repository_rollback_on_error():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([BankAccount, AuditLog])

    account_repo = db.repository(BankAccount)
    audit_repo = db.repository(AuditLog)

    with pytest.raises(ValueError, match="Simulated transfer failure"):
        async with db.unit_of_work() as uow:
            acc_uow = uow.repository(BankAccount)
            audit_uow = uow.repository(AuditLog)

            await acc_uow.create(BankAccount(owner="Bob", balance=500.0))
            await audit_uow.create(AuditLog(action="Creating account Bob"))
            raise ValueError("Simulated transfer failure")

    assert await account_repo.count() == 0
    assert await audit_repo.count() == 0

    await db.disconnect()

@pytest.mark.asyncio
async def test_uow_auto_rollback_on_uncommitted_exit():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([BankAccount, AuditLog])

    account_repo = db.repository(BankAccount)

    async with db.unit_of_work() as uow:
        acc_uow = uow.repository(BankAccount)
        await acc_uow.create(BankAccount(owner="Charlie", balance=300.0))

    assert await account_repo.count() == 0

    await db.disconnect()

@pytest.mark.asyncio
async def test_nested_transaction_unsupported():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([BankAccount])

    account_repo = db.repository(BankAccount)

    async with db.transaction():
        await account_repo.create(BankAccount(owner="Outer", balance=100.0))

        with pytest.raises(Exception):
            async with db.transaction():
                await account_repo.create(BankAccount(owner="Inner", balance=200.0))

    assert await account_repo.count() == 1

    await db.disconnect()

@pytest.mark.asyncio
async def test_unsupported_transactions_raise():

    class NoTxAdapter(SQLiteAdapter):
        capabilities = DatabaseCapabilities(transactions=False)

    db = Database(NoTxAdapter(":memory:"))

    with pytest.raises(UnsupportedOperationError, match="requires capability 'transactions'"):
        async with db.transaction():
            pass

class NativeAccount(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    owner: str
    balance: float = 0.0

class NativeAuditTrail(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    action: str

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_uow_multi_repo_atomic_commit(kind):
    db = await nh.connect_schema(kind, [NativeAccount, NativeAuditTrail])
    try:
        async with db.unit_of_work() as uow:
            accounts = uow.repository(NativeAccount)
            audit = uow.repository(NativeAuditTrail)
            await accounts.create(NativeAccount(id="a1", owner="Alice", balance=1000.0))
            await audit.create(NativeAuditTrail(id="t1", action="Account Alice created"))
            await uow.commit()

        assert await db.repository(NativeAccount).count() == 1
        assert await db.repository(NativeAuditTrail).count() == 1
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_uow_multi_repo_atomic_rollback_on_mid_batch_failure(kind):
    db = await nh.connect_schema(kind, [NativeAccount, NativeAuditTrail])
    try:
        with pytest.raises(RuntimeError, match="Mid-batch failure"):
            async with db.unit_of_work() as uow:
                accounts = uow.repository(NativeAccount)
                audit = uow.repository(NativeAuditTrail)
                await accounts.create(NativeAccount(id="a1", owner="Bob", balance=500.0))
                await audit.create(NativeAuditTrail(id="t1", action="Account Bob created"))
                raise RuntimeError("Mid-batch failure")

        assert await db.repository(NativeAccount).count() == 0
        assert await db.repository(NativeAuditTrail).count() == 0

        assert await nh.native_all(db, "nativeaccounts") == []
        assert await nh.native_all(db, "nativeaudittrails") == []
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_committed_row_visibility(kind):
    db = await nh.connect_schema(kind, [NativeAccount])
    try:
        repo = db.repository(NativeAccount)
        await repo.create(NativeAccount(id="a1", owner="Alice", balance=1000.0))

        rows = await nh.native_all(db, "nativeaccounts")
        assert len(rows) == 1
        assert rows[0]["owner"] == "Alice"
        assert rows[0]["balance"] == 1000.0
    finally:
        await nh.cleanup(db)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_uow_rollback_and_transaction_commit(kind):
    db = await nh.connect_schema(kind, [NativeAccount])
    try:

        async with db.unit_of_work() as uow:
            acc_uow = uow.repository(NativeAccount)
            await acc_uow.create(NativeAccount(id="b1", owner="Bob", balance=500.0))
        assert await nh.native_all(db, "nativeaccounts") == []

        async with db.transaction():
            await db.repository(NativeAccount).create(
                NativeAccount(id="o1", owner="Outer", balance=100.0)
            )

        rows = await nh.native_all(db, "nativeaccounts")
        assert len(rows) == 1
        assert rows[0]["owner"] == "Outer"
    finally:
        await nh.cleanup(db)
