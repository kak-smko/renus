from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from renus.db import (
    AsyncDatabaseAdapter,
    CompiledMutation,
    CompiledQuery,
    ConfigurationError,
    Database,
    DatabaseField,
    Delete,
    DeleteMany,
    Field,
    Insert,
    InsertMany,
    MutationResult,
    QueryResult,
    Model,
    Repository,
    TransactionContext,
    UnitOfWork,
    UnsupportedOperationError,
    Update,
    UpdateMany,
    Upsert,
)

from tests.db._fakes import DDLFakeMixin

class Account(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    owner: str
    balance: float = 0.0
    active: bool = True

class LogEntry(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    message: str

    class Meta:
        soft_delete = True
        timestamps = True

class InMemoryAdapter(DDLFakeMixin, AsyncDatabaseAdapter):

    name = "in_memory"

    def __init__(
        self,
    ) -> None:
        self.connected = False
        self.executed_queries: list[Any] = []
        self.executed_mutations: list[Any] = []
        self.tx_committed = False
        self.tx_rolled_back = False
        self._next_id = 1
        self.records: dict[type, dict[Any, dict[str, Any]]] = {}

    async def connect(self, config: Any = None) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        self.executed_queries.append(compiled)

        ast = compiled
        source = getattr(ast, "source", None)
        model_records = self.records.get(source, {})

        if getattr(ast, "aggregates", None):
            return [{"count": len(model_records)}]

        results = list(model_records.values())

        for cond in getattr(ast, "filters", ()):
            attr = cond.path.parts[-1]
            val = cond.value
            results = [r for r in results if r.get(attr) == val]

        if getattr(ast, "limit", None) is not None:
            results = results[: ast.limit]

        return results

    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        self.executed_mutations.append(compiled)

        if isinstance(compiled, Insert):
            source = compiled.source
            if source not in self.records:
                self.records[source] = {}

            record = dict(compiled.values)
            new_id = self._next_id
            self._next_id += 1
            record["id"] = new_id
            self.records[source][new_id] = record
            return MutationResult(rows_affected=1, last_id=new_id)

        if isinstance(compiled, InsertMany):
            source = compiled.source
            if source not in self.records:
                self.records[source] = {}

            count = 0
            for r in compiled.records:
                rec = dict(r)
                new_id = self._next_id
                self._next_id += 1
                rec["id"] = new_id
                self.records[source][new_id] = rec
                count += 1
            return MutationResult(rows_affected=count)

        if isinstance(compiled, (Update, UpdateMany)):
            source = compiled.source
            model_records = self.records.get(source, {})
            affected = 0
            for r_id, r in list(model_records.items()):

                matches = True
                for f in compiled.filters:
                    attr = f.path.parts[-1]
                    if r.get(attr) != f.value:
                        matches = False
                        break
                if matches:
                    r.update(compiled.values)
                    affected += 1
            return MutationResult(rows_affected=affected)

        if isinstance(compiled, (Delete, DeleteMany)):
            source = compiled.source
            model_records = self.records.get(source, {})
            affected = 0
            for r_id, r in list(model_records.items()):
                matches = True
                for f in compiled.filters:
                    attr = f.path.parts[-1]
                    if r.get(attr) != f.value:
                        matches = False
                        break
                if matches:
                    del model_records[r_id]
                    affected += 1
            return MutationResult(rows_affected=affected)

        if isinstance(compiled, Upsert):
            return MutationResult(rows_affected=1)

        return MutationResult(rows_affected=1)

    def transaction_factory(self) -> AsyncIterator[TransactionContext]:
        adapter_self = self

        async def _gen() -> AsyncIterator[TransactionContext]:
            class _Ctx:
                async def __aenter__(self) -> Any:
                    return self

                async def __aexit__(self, *args: object) -> bool:
                    return False

                async def commit(self) -> None:
                    adapter_self.tx_committed = True

                async def rollback(self) -> None:
                    adapter_self.tx_rolled_back = True

            yield _Ctx()

        return _gen()

    async def health_check(self) -> bool:
        return self.connected

def test_prohibited_methods_not_present():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    assert not hasattr(repo, "get_by_id")

    assert not hasattr(repo, "delete_by_id")

    assert not hasattr(repo, "version")
    assert not hasattr(repo, "optimistic_lock")

@pytest.mark.asyncio
async def test_repository_create():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    acc = Account(owner="Alice", balance=100.0)
    assert acc.is_new() is True

    created = await repo.create(acc)
    assert created.id == 1
    assert created.is_persisted() is True
    assert created.is_new() is False
    assert len(adapter.executed_mutations) == 1
    assert isinstance(adapter.executed_mutations[0], Insert)

@pytest.mark.asyncio
async def test_repository_create_many():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    acc1 = Account(owner="Bob", balance=50.0)
    acc2 = Account(owner="Carol", balance=75.0)

    created_list = await repo.create_many([acc1, acc2])
    assert len(created_list) == 2
    assert created_list[0].is_persisted() is True
    assert created_list[1].is_persisted() is True
    assert len(adapter.executed_mutations) == 1
    assert isinstance(adapter.executed_mutations[0], InsertMany)

@pytest.mark.asyncio
async def test_repository_query_and_hydration():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    await repo.create(Account(owner="Dave", balance=200.0))
    await repo.create(Account(owner="Eve", balance=300.0))

    q = repo.query(Account.owner == "Dave")
    results = await q.all()
    assert len(results) == 1
    assert results[0].owner == "Dave"
    assert results[0].is_persisted() is True

@pytest.mark.asyncio
async def test_repository_save():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    acc = Account(owner="Frank", balance=500.0)
    await repo.save(acc)
    assert acc.is_persisted() is True
    assert acc.id is not None

    initial_mutations = len(adapter.executed_mutations)
    await repo.save(acc)
    assert len(adapter.executed_mutations) == initial_mutations

    acc.balance = 600.0
    assert acc.is_dirty() is True
    await repo.save(acc)
    assert acc.is_persisted() is True
    assert acc.is_dirty() is False
    assert len(adapter.executed_mutations) == initial_mutations + 1
    assert isinstance(adapter.executed_mutations[-1], Update)

@pytest.mark.asyncio
async def test_repository_update_and_update_many():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    await repo.create(Account(owner="Grace", balance=10.0, active=True))

    rows = await repo.update(Account.owner == "Grace", values={"balance": 20.0})
    assert rows == 1

    rows_many = await repo.update_many(Account.active == True, values={"balance": 30.0})
    assert rows_many == 1

@pytest.mark.asyncio
async def test_repository_delete_and_delete_many():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    acc = await repo.create(Account(owner="Heidi", balance=10.0))

    rows = await repo.delete(acc)
    assert rows == 1
    assert acc.is_deleted() is True

    await repo.create(Account(owner="Ivan", balance=0.0))
    del_rows = await repo.delete_many(Account.owner == "Ivan")
    assert del_rows == 1

@pytest.mark.asyncio
async def test_repository_soft_delete():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, LogEntry)

    log = await repo.create(LogEntry(message="System started"))
    assert not log.is_deleted()

    rows = await repo.delete(log)
    assert rows == 1
    assert log.is_deleted() is True
    assert isinstance(adapter.executed_mutations[-1], Update)
    assert "deleted_at" in adapter.executed_mutations[-1].values

@pytest.mark.asyncio
async def test_repository_upsert():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    acc = Account(id=10, owner="Judy", balance=50.0)
    rows = await repo.upsert(target=acc)
    assert rows == 1
    assert isinstance(adapter.executed_mutations[-1], Upsert)


@pytest.mark.asyncio
async def test_repository_count_and_exists():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    await repo.create(Account(owner="Leo", balance=100.0))
    await repo.create(Account(owner="Mona", balance=200.0))

    total = await repo.count()
    assert total == 2

    assert await repo.exists(Account.owner == "Leo") is True
    assert await repo.exists(Account.owner == "NonExistent") is False

@pytest.mark.asyncio
async def test_native_raw_rows_in_backing_store():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, Account)

    acc = await repo.create(Account(owner="Alice", balance=100.0, active=True))
    assert adapter.records[Account][acc.id]["owner"] == "Alice"
    assert adapter.records[Account][acc.id]["balance"] == 100.0

    await repo.update(Account.id == acc.id, values={"balance": 250.0})
    assert adapter.records[Account][acc.id]["balance"] == 250.0

    await repo.delete_many(Account.owner == "Alice")
    assert acc.id not in adapter.records[Account]

@pytest.mark.asyncio
async def test_native_raw_rows_soft_delete_timestamp():
    adapter = InMemoryAdapter()
    repo = Repository(adapter, LogEntry)

    log = await repo.create(LogEntry(message="boot"))
    await repo.delete(log)

    record = adapter.records[LogEntry][log.id]
    assert "deleted_at" in record
    assert record["deleted_at"] is not None
    assert "created_at" in record

@pytest.mark.asyncio
async def test_unit_of_work_commit():
    adapter = InMemoryAdapter()
    uow = UnitOfWork(adapter)

    async with uow:
        repo = uow.repository(Account)
        await repo.create(Account(owner="Nora", balance=100.0))
        await uow.commit()

    assert uow.is_committed is True
    assert adapter.tx_committed is True

@pytest.mark.asyncio
async def test_unit_of_work_rollback_on_uncommitted_exit():
    adapter = InMemoryAdapter()
    uow = UnitOfWork(adapter)

    async with uow:
        repo = uow.repository(Account)
        await repo.create(Account(owner="Oscar", balance=100.0))

    assert uow.is_committed is False
    assert adapter.tx_rolled_back is True

@pytest.mark.asyncio
async def test_unit_of_work_rollback_on_exception():
    adapter = InMemoryAdapter()
    uow = UnitOfWork(adapter)

    with pytest.raises(RuntimeError, match="Business error"):
        async with uow:
            repo = uow.repository(Account)
            await repo.create(Account(owner="Paul", balance=100.0))
            raise RuntimeError("Business error")

    assert uow.is_committed is False
    assert adapter.tx_rolled_back is True

@pytest.mark.asyncio
async def test_unit_of_work_dynamic_attribute_lookup():
    adapter = InMemoryAdapter()
    uow = UnitOfWork(adapter)

    repo = uow.repository(Account)
    assert uow.account is repo
    assert uow.accounts is repo

    with pytest.raises(AttributeError, match="no repository registered"):
        _ = uow.unknown_model

@pytest.mark.asyncio
async def test_explicit_transaction():
    adapter = InMemoryAdapter()
    db = Database(adapter)

    async with db.transaction():
        repo = db.repository(Account)
        await repo.create(Account(owner="Quinn"))

    assert adapter.tx_committed is True


@pytest.mark.asyncio
async def test_database_facade_lifecycle_and_connections():
    primary = InMemoryAdapter()
    replica = InMemoryAdapter()

    db = Database(primary)
    db.register_adapter("replica", replica)

    await db.connect()
    assert primary.connected is True
    assert replica.connected is True

    assert await db.health_check("primary") is True
    assert db.adapter().nested_documents == primary.nested_documents

    rep_primary = db.repository(Account, connection="primary")
    rep_replica = db.repository(Account, connection="replica")
    assert rep_primary.connection_name == "primary"
    assert rep_replica.connection_name == "replica"

    await db.disconnect()
    assert primary.connected is False
    assert replica.connected is False

@pytest.mark.asyncio
async def test_database_gets_adapter_from_config(monkeypatch: Any):
    test_adapter = InMemoryAdapter()
    from renus.config import Config

    def fake_get(self: Any, key: str, default: Any = None) -> Any:
        if key == "adapter":
            return test_adapter
        return default

    monkeypatch.setattr(Config, "get", fake_get)

    db = Database()
    assert db.adapter("primary") is test_adapter
    assert db.adapter().nested_documents == test_adapter.nested_documents

@pytest.mark.asyncio
async def test_database_invalid_adapter_in_config_raises(monkeypatch: Any):
    from renus.config import Config

    def fake_get(self: Any, key: str, default: Any = None) -> Any:
        if key == "adapter":
            return 12345
        return default

    monkeypatch.setattr(Config, "get", fake_get)

    with pytest.raises(ConfigurationError, match="Invalid adapter configured"):
        Database()

@pytest.mark.asyncio
async def test_database_unknown_driver_in_config_raises(monkeypatch: Any):
    from renus.config import Config

    def fake_get(self: Any, key: str, default: Any = None) -> Any:
        if key == "driver":
            return "unknown_custom_driver_xyz"
        return default

    monkeypatch.setattr(Config, "get", fake_get)

    with pytest.raises(ConfigurationError, match="Unknown DB adapter"):
        Database()

@pytest.mark.asyncio
async def test_database_adapter_factory_returns_invalid_type_raises(monkeypatch: Any):
    from renus.config import Config

    def fake_get(self: Any, key: str, default: Any = None) -> Any:
        if key == "adapter":
            return lambda: "not_an_adapter"
        return default

    monkeypatch.setattr(Config, "get", fake_get)

    with pytest.raises(ConfigurationError, match="returned invalid type"):
        Database()

@pytest.mark.asyncio
async def test_database_no_adapter_and_no_config_raises(monkeypatch: Any):
    from renus.config import Config

    def fake_get(self: Any, key: str, default: Any = None) -> Any:
        return default

    monkeypatch.setattr(Config, "get", fake_get)

    with pytest.raises(ConfigurationError, match="No adapter configured for connection 'primary'"):
        Database()

