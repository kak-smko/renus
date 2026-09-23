from __future__ import annotations

from typing import Any

import pytest

from renus.db.core import (
    AsyncDatabaseAdapter,
    CompiledMutation,
    CompiledQuery,
    ConfigurationError,
    ConnectionError,
    DatabaseError,
    DuplicateKeyError,
    Event,
    EventBus,
    IdentityKind,
    IntegrityError,
    Lifecycle,
    LifecycleEvent,
    MutationResult,
    NotFoundError,
    QueryError,
    QueryResult,
    TransactionError,
    DBError,
    UnsupportedOperationError,
    ValidationError,
)
from renus.db.core.exceptions import MutationError

from tests.db._fakes import DDLFakeMixin

def test_all_exceptions_derive_from_dberror():
    assert issubclass(DatabaseError, DBError)
    assert issubclass(ConfigurationError, DBError)
    assert issubclass(ConnectionError, DBError)
    assert issubclass(QueryError, DatabaseError)
    assert issubclass(MutationError, DatabaseError)
    assert issubclass(ValidationError, DBError)
    assert issubclass(NotFoundError, DatabaseError)
    assert issubclass(IntegrityError, DatabaseError)
    assert issubclass(DuplicateKeyError, IntegrityError)
    assert issubclass(TransactionError, DatabaseError)
    assert issubclass(UnsupportedOperationError, DBError)

def test_connection_error_is_not_builtin():

    assert issubclass(ConnectionError, DBError)


def test_lifecycle_states():
    assert {s.value for s in Lifecycle} == {
        "new",
        "persisted",
        "dirty",
        "deleted",
        "detached",
    }

def test_identity_kinds():
    assert {k.value for k in IdentityKind} == {
        "integer",
        "uuid",
        "string",
        "composite",
        "generated",
        "id",
    }

@pytest.mark.asyncio
async def test_event_bus_sync_listener():
    bus = EventBus()
    received: list[Event] = []

    def on_query(event: Event) -> None:
        received.append(event)

    bus.on("query", on_query)
    await bus.emit("query", LifecycleEvent(model="x", state=Lifecycle.NEW))
    assert len(received) == 1

@pytest.mark.asyncio
async def test_event_bus_async_listener():
    bus = EventBus()
    seen: list[str] = []

    async def on_mutation(event: Event) -> None:
        assert isinstance(event, LifecycleEvent)
        seen.append(event.state.value)

    bus.on("mutation", on_mutation)
    await bus.emit("mutation", LifecycleEvent(model="m", state=Lifecycle.DELETED))
    assert seen == ["deleted"]

@pytest.mark.asyncio
async def test_event_bus_mixed_sync_and_async_in_order():
    bus = EventBus()
    order: list[str] = []

    def sync_hook(event: Event) -> None:
        order.append("sync")

    async def async_hook(event: Event) -> None:
        order.append("async")

    bus.on("lifecycle", sync_hook)
    bus.on("lifecycle", async_hook)
    await bus.emit("lifecycle", LifecycleEvent(model=1, state=Lifecycle.PERSISTED))
    assert order == ["sync", "async"]

@pytest.mark.asyncio
async def test_event_bus_dedup_and_off():
    bus = EventBus()
    count = 0

    def hook(event: Event) -> None:
        nonlocal count
        count += 1

    bus.on("lifecycle", hook)
    bus.on("lifecycle", hook)
    await bus.emit("lifecycle", LifecycleEvent(model=1, state=Lifecycle.NEW))
    assert count == 1

    bus.off("lifecycle", hook)
    await bus.emit("lifecycle", LifecycleEvent(model=1, state=Lifecycle.NEW))
    assert count == 1

def test_mutation_result_defaults():
    result = MutationResult(rows_affected=0)
    assert result.last_id is None
    assert result.generated is None

def test_mutation_result_generated():
    result = MutationResult(rows_affected=1, last_id=42, generated={"id": 42})
    assert result.last_id == 42
    assert result.generated == {"id": 42}

def test_adapter_is_abstract():

    with pytest.raises(TypeError):
        AsyncDatabaseAdapter()

class ConcreteAdapter(DDLFakeMixin, AsyncDatabaseAdapter):
    name = "fake"

    async def connect(self, config: Any = None) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        return ()

    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        return MutationResult(rows_affected=1)

    def transaction_factory(self) -> Any:
        async def _gen() -> Any:
            class _Ctx:
                async def __aenter__(self) -> Any:
                    return self

                async def __aexit__(self, *args: object) -> bool:
                    return False

                async def commit(self) -> None:
                    return None

                async def rollback(self) -> None:
                    return None

            yield _Ctx()

        return _gen()

    async def health_check(self) -> bool:
        return True

def test_concrete_adapter_instantiates():
    adapter = ConcreteAdapter()
    assert isinstance(adapter, AsyncDatabaseAdapter)
    assert adapter.name == "fake"
    assert adapter.nested_documents is False

@pytest.mark.asyncio
async def test_adapter_create_schema_unsupported_by_default():

    adapter = ConcreteAdapter()
    with pytest.raises(UnsupportedOperationError):
        await adapter.create_schema(models=[])

@pytest.mark.asyncio
async def test_adapter_lifecycle_and_health():
    adapter = ConcreteAdapter()
    await adapter.connect()
    assert await adapter.health_check() is True
    await adapter.disconnect()

@pytest.mark.asyncio
async def test_adapter_execute_mutation():
    adapter = ConcreteAdapter()
    result = await adapter.execute_mutation(object())
    assert result.rows_affected == 1

def test_adapter_nested_documents_class_attribute_override():

    class WithNested(ConcreteAdapter):
        nested_documents = True

    assert WithNested.nested_documents is True
