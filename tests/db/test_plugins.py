from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from renus.db import (
    AsyncDatabaseAdapter,
    CompiledMutation,
    CompiledQuery,
    ConfigurationError,
    Database,
    DatabaseField,
    MutationResult,
    Plugin,
    PluginManager,
    Field,
    QueryResult,
    Model,
    SQLiteAdapter,
    adapters,
    clear_adapters,
    get_adapter,
    has_adapter,
    register_adapter,
    reset_builtin_adapters,
    unregister_adapter,
)

from tests.db._fakes import DDLFakeMixin

class MockCustomAdapter(DDLFakeMixin, AsyncDatabaseAdapter):

    name: ClassVar[str] = "custom_test_backend"
    nested_documents=True

    def __init__(self, config: Any = None) -> None:
        self.config = config
        self.connected = False
        self.executed_queries: list[Any] = []
        self.executed_mutations: list[Any] = []

    async def connect(self, config: Any = None) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def health_check(self) -> bool:
        return self.connected

    def transaction_factory(self) -> Any:
        raise NotImplementedError

    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        self.executed_queries.append(compiled)
        return [{"id": 1, "title": "Test Row"}]

    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        self.executed_mutations.append(compiled)
        return MutationResult(rows_affected=1, last_id=1)


class FailingAdapter(MockCustomAdapter):
    name: ClassVar[str] = "failing_test_backend"

    async def execute_query(self, compiled: CompiledQuery[Any]) -> QueryResult[Any]:
        raise RuntimeError("query execution failed")

    async def execute_mutation(self, compiled: CompiledMutation) -> MutationResult:
        raise RuntimeError("mutation execution failed")

def test_adapter_registry_lifecycle():

    clear_adapters()
    assert adapters() == ()

    reset_builtin_adapters()
    assert "sqlite" in adapters()
    assert "mysql" in adapters()
    assert "mongodb" in adapters()

    register_adapter("custom_mock", MockCustomAdapter)
    assert has_adapter("custom_mock")
    assert has_adapter("CUSTOM_MOCK")
    assert get_adapter("custom_mock") is MockCustomAdapter
    assert "custom_mock" in adapters()

    unregister_adapter("custom_mock")
    assert not has_adapter("custom_mock")

    with pytest.raises(ConfigurationError, match="Unknown DB adapter"):
        get_adapter("nonexistent_db_backend_123")

    clear_adapters()
    assert adapters() == ()
    reset_builtin_adapters()
    assert "sqlite" in adapters()
    assert "mysql" in adapters()
    assert "mongodb" in adapters()

def test_dynamic_dotted_module_adapter_loading():
    adapter_cls = get_adapter("tests.db.test_plugins:MockCustomAdapter")
    assert issubclass(adapter_cls, AsyncDatabaseAdapter)
    assert adapter_cls.__name__ == "MockCustomAdapter"
    assert has_adapter("tests.db.test_plugins:mockcustomadapter")

    with pytest.raises(ConfigurationError, match="Failed to import DB adapter"):
        get_adapter("nonexistent_module.fake:FakeAdapter")

def test_entry_point_adapter_discovery():
    mock_ep = MagicMock()
    mock_ep.name = "plugin_db"
    mock_ep.load.return_value = MockCustomAdapter

    with patch("renus.db.plugins.registry.entry_points", return_value=[mock_ep]):

        unregister_adapter("plugin_db")
        loaded = get_adapter("plugin_db")
        assert loaded is MockCustomAdapter
        assert has_adapter("plugin_db")

class AuditLogPlugin(Plugin):
    name = "audit_log"
    version = "1.2.0"

    def __init__(self) -> None:
        super().__init__()
        self.connected_events: list[str] = []
        self.disconnected_events: list[str] = []
        self.queries_intercepted: list[Any] = []
        self.mutations_intercepted: list[Any] = []
        self.errors_intercepted: list[Exception] = []

    async def on_connect(self, db: Database, connection: str) -> None:
        self.connected_events.append(connection)

    async def on_disconnect(self, db: Database, connection: str) -> None:
        self.disconnected_events.append(connection)

    async def before_query(self, db: Database, ast: Any, context: dict[str, Any]) -> None:
        self.queries_intercepted.append(ast)

    async def before_mutation(self, db: Database, ast: Any, context: dict[str, Any]) -> None:
        self.mutations_intercepted.append(ast)

    async def on_error(self, db: Database, error: Exception, context: dict[str, Any]) -> None:
        self.errors_intercepted.append(error)

def test_plugin_manager_crud():
    pm = PluginManager()
    assert pm.all() == []

    plugin = AuditLogPlugin()
    registered = pm.register(plugin)
    assert registered is plugin
    assert pm.has("audit_log")
    assert pm.has("AUDIT_LOG")
    assert pm.get("audit_log") is plugin
    assert len(pm.all()) == 1

    unregistered = pm.unregister("audit_log")
    assert unregistered is plugin
    assert not pm.has("audit_log")

    with pytest.raises(KeyError, match="not registered"):
        pm.get("audit_log")

@pytest.mark.asyncio
async def test_database_use_plugin_integration():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)

    plugin = AuditLogPlugin()
    ret = db.use(plugin)
    assert ret is db
    assert db.plugins.has("audit_log")
    assert db.plugins.get("audit_log") is plugin

    await db.connect()
    assert plugin.connected_events == ["primary"]

    await db.disconnect()
    assert plugin.disconnected_events == ["primary"]

class Article(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    title: str

@pytest.mark.asyncio
async def test_third_party_adapter_without_core_modification():
    custom_adapter = MockCustomAdapter()
    db = Database(custom_adapter)
    await db.connect()

    repo = db.repository(Article)
    assert repo.adapter is custom_adapter
    assert repo.model is Article

    results = await repo.query(Article.id == 1).all()
    assert len(results) == 1
    assert results[0].id == 1
    assert results[0].title == "Test Row"
    assert len(custom_adapter.executed_queries) == 1

    await db.disconnect()


@pytest.mark.asyncio
async def test_plugin_error_hook_receives_query_and_mutation_errors():
    db = Database(FailingAdapter())
    plugin = AuditLogPlugin()
    db.use(plugin)
    repo = db.repository(Article)

    with pytest.raises(RuntimeError, match="query execution failed") as query_error:
        await repo.query(Article.id == 1).all()

    with pytest.raises(RuntimeError, match="mutation execution failed") as mutation_error:
        await repo.update(Article.id == 1, {"title": "Updated"})

    assert plugin.errors_intercepted == [query_error.value, mutation_error.value]

class MutationEventPlugin(Plugin):

    name = "mutation_events"

    def __init__(self) -> None:
        super().__init__()
        self.before: list[str] = []
        self.after: list[str] = []
        self.after_rows_affected: list[int] = []

    async def before_mutation(self, db, ast, context) -> None:
        self.before.append(ast.__class__.__name__)

    async def after_mutation(self, db, ast, result, context) -> None:
        self.after.append(ast.__class__.__name__)
        self.after_rows_affected.append(result.rows_affected)
