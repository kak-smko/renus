from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from renus.db import (
    DatabaseError,
    DatabaseField,
    DuplicateKeyError,
    IntegrityError,
    Field,
    MutationResult,
    MySQLAdapter,
    Path,
    Model,
    Repository,
    Delete,
    Insert,
    InsertMany,
    Update,
)
from renus.db.mysql.adapter import MySQLTransactionContext
from renus.db.sql import (
    SQLCompiled,
    SQLCompiler,
    SQLMutationCompiler,
)
from renus.db.mysql.dialect import MySQLDialect
from renus.db.validation import MaxLen
from tests.db import _conformance


class Customer(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True, auto_inc=True))
    username: str = Field(MaxLen(255),database=DatabaseField(unique=True))
    balance: float = 0.0
    active: bool = True

    class Meta:
        timestamps = True
        soft_delete = True

def test_mysql_dialect_quoting_and_placeholders():
    dialect = MySQLDialect()
    assert dialect.quote("users") == "`users`"
    assert dialect.quote("user`table") == "`user``table`"
    assert dialect.placeholder == "%s"
    assert dialect.placeholders(4) == "%s, %s, %s, %s"

def test_mysql_dialect_type_mapping():
    dialect = MySQLDialect()
    meta = Customer.metadata()

    id_sql = dialect.type_to_sql(meta.fields["id"])
    assert id_sql == "INT AUTO_INCREMENT PRIMARY KEY"

    username_sql = dialect.type_to_sql(meta.fields["username"])
    assert username_sql == "VARCHAR(255)"

    balance_sql = dialect.type_to_sql(meta.fields["balance"])
    assert balance_sql == "DOUBLE"

    active_sql = dialect.type_to_sql(meta.fields["active"])
    assert active_sql == "TINYINT(1)"


def test_mysql_compiler_query_compilation():
    dialect = MySQLDialect()
    compiler = SQLCompiler(dialect)

    repo = Repository(MySQLAdapter(), Customer)
    q_ast = (
        repo.query((Customer.balance >= 50.0) & (Customer.active == True))
        .order_by(Customer.username.asc())
        .limit(25)
        .offset(50)
        .ast
    )

    compiled = compiler.compile(q_ast)
    assert 'SELECT * FROM `customers`' in compiled.sql
    assert '`deleted_at` IS NULL' in compiled.sql
    assert '`balance` >= %s' in compiled.sql
    assert '`active` = %s' in compiled.sql
    assert 'ORDER BY `username` ASC' in compiled.sql
    assert "LIMIT 25 OFFSET 50" in compiled.sql
    assert compiled.params == (50.0, True)

def test_mysql_compiler_mutations():
    dialect = MySQLDialect()
    mut_comp = SQLMutationCompiler(dialect)

    ins = Insert(Customer, values={"username": "bob", "balance": 50.0})
    compiled_ins = mut_comp.compile(ins)
    assert "INSERT INTO `customers` (`username`, `balance`) VALUES (%s, %s)" in compiled_ins.sql
    assert compiled_ins.params == ("bob", 50.0)

    ins_many = InsertMany(Customer, records=[{"username": "c1"}, {"username": "c2"}])
    compiled_many = mut_comp.compile(ins_many)
    assert "INSERT INTO `customers` (`username`) VALUES (%s), (%s)" in compiled_many.sql
    assert compiled_many.params == ("c1", "c2")

    upd = Update(Customer, values={"balance": 75.0}, filters=(Customer.username == "bob",))
    compiled_upd = mut_comp.compile(upd)
    assert "UPDATE `customers` SET `balance` = %s WHERE `username` = %s" in compiled_upd.sql
    assert compiled_upd.params[0] == 75.0
    assert compiled_upd.params[1] == "bob"

    del_ast = Delete(Customer, filters=(Customer.username == "bob",))
    compiled_del = mut_comp.compile(del_ast)
    assert "DELETE FROM `customers` WHERE `username` = %s" in compiled_del.sql
    assert compiled_del.params == ("bob",)

def test_mysql_adapter_capabilities():
    adapter = MySQLAdapter()
    assert adapter.name == "mysql"

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "overrides"),
    [
        ({}, {}),
        (
            {
                "host": "127.0.0.1",
                "port": "3307",
                "username": "tester",
                "password": "pwd",
                "database": "test_db",
                "max_pool": "200",
                "min_pool": "20",
                "connect_timeout": "9",
                "retries": 1,
            },
            {
                "host": "127.0.0.1",
                "port": 3307,
                "user": "tester",
                "password": "pwd",
                "db": "test_db",
                "minsize": 20,
                "maxsize": 200,
                "connect_timeout": 9,
            },
        ),
    ],
)
async def test_mysql_adapter_connection_options(monkeypatch, config, overrides):
    from renus.db.mysql import adapter as mysql_adapter_module
    from renus.db.mysql.adapter import (
        DEFAULT_MYSQL_CONNECT_TIMEOUT,
        DEFAULT_MYSQL_MAX_POOL,
        DEFAULT_MYSQL_MIN_POOL,
    )

    assert DEFAULT_MYSQL_MIN_POOL >= 1
    assert DEFAULT_MYSQL_MAX_POOL >= 50
    assert DEFAULT_MYSQL_MIN_POOL <= DEFAULT_MYSQL_MAX_POOL
    assert DEFAULT_MYSQL_CONNECT_TIMEOUT >= 1

    create_pool = AsyncMock()
    monkeypatch.setattr(
        mysql_adapter_module,
        "aiomysql",
        MagicMock(create_pool=create_pool),
    )

    pool = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=(1,))
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=None)
    conn.cursor = MagicMock(return_value=cursor)
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = MagicMock()
    pool.close = MagicMock()
    pool.wait_closed = AsyncMock()
    create_pool.return_value = pool

    adapter = MySQLAdapter(config)
    await adapter.connect()

    create_pool.assert_awaited_once_with(
        host=overrides.get("host", "localhost"),
        port=overrides.get("port", 3306),
        user=overrides.get("user", "root"),
        password=overrides.get("password", ""),
        db=overrides.get("db", "db"),
        minsize=overrides.get("minsize", DEFAULT_MYSQL_MIN_POOL),
        maxsize=overrides.get("maxsize", DEFAULT_MYSQL_MAX_POOL),
        autocommit=False,
        connect_timeout=overrides.get(
            "connect_timeout", DEFAULT_MYSQL_CONNECT_TIMEOUT
        ),
    )
    await adapter.disconnect()

@pytest.mark.asyncio
async def test_mysql_mock_execution():
    adapter = MySQLAdapter()

    mock_cursor = MagicMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[{"id": 1, "username": "alice", "balance": 100.0}])
    mock_cursor.fetchone = AsyncMock(return_value={"1": 1})
    mock_cursor.rowcount = 1
    mock_cursor.lastrowid = 1
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_conn.commit = AsyncMock()
    mock_conn.rollback = AsyncMock()
    mock_conn.begin = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire = AsyncMock(return_value=mock_conn)
    mock_pool.release = MagicMock()
    mock_pool.close = MagicMock()
    mock_pool.wait_closed = AsyncMock()

    adapter._mysql_db = mock_pool

    assert await adapter.health_check() is True

    repo = Repository(adapter, Customer)
    query = repo.query(Customer.username == "alice")
    compiled_query = adapter.compile_query(query.ast)
    rows = await adapter.execute_query(query.ast)
    assert len(rows) == 1
    assert rows[0]["username"] == "alice"
    assert mock_cursor.execute.await_args_list[-1].args == (
        compiled_query.sql,
        compiled_query.params,
    )

    insert = Insert(Customer, values={"username": "alice", "balance": 100.0})
    compiled_insert = adapter.compile_mutation(insert)
    res = await adapter.execute_mutation(insert)
    assert isinstance(res, MutationResult)
    assert res.rows_affected == 1
    assert res.last_id == 1
    assert mock_cursor.execute.await_args_list[-1].args == (
        compiled_insert.sql,
        compiled_insert.params,
    )

    mysql_conn = await adapter._mysql_db.acquire()
    async with mysql_conn.cursor() as cur:
        await cur.execute("SELECT 1;")
        raw_res = await cur.fetchall()
    adapter._mysql_db.release(mysql_conn)
    assert len(raw_res) == 1

    await adapter.disconnect()
    assert adapter._mysql_db is None

@pytest.mark.asyncio
async def test_mysql_transaction_context():
    mock_conn = MagicMock()
    mock_conn.begin = AsyncMock()
    mock_conn.commit = AsyncMock()
    mock_conn.rollback = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.release = MagicMock()

    ctx = MySQLTransactionContext(mock_conn, mock_pool)

    async with ctx:
        await ctx.commit()

    mock_conn.begin.assert_called_once()
    mock_conn.commit.assert_called_once()
    mock_pool.release.assert_called_once_with(mock_conn)

    mock_conn.reset_mock()
    mock_pool.reset_mock()
    ctx2 = MySQLTransactionContext(mock_conn, mock_pool)

    with pytest.raises(RuntimeError):
        async with ctx2:
            raise RuntimeError("tx fail")

    mock_conn.rollback.assert_called_once()
    mock_pool.release.assert_called_once_with(mock_conn)

@pytest.mark.asyncio
async def test_mysql_error_translation():
    adapter = MySQLAdapter()

    mock_cursor = MagicMock()
    mock_cursor.execute = AsyncMock(side_effect=Exception("1062 Duplicate entry 'alice' for key 'username'"))
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor)
    mock_pool = MagicMock()
    mock_pool.acquire = AsyncMock(return_value=mock_conn)
    mock_pool.release = MagicMock()

    adapter._mysql_db = mock_pool

    with pytest.raises(DuplicateKeyError, match="duplicate key error"):
        await adapter.execute_mutation(Insert(Customer, values={"username": "alice"}))

    mock_cursor.execute = AsyncMock(side_effect=Exception("Table 'db.missing' doesn't exist"))
    with pytest.raises(DatabaseError, match="MySQL mutation error"):
        await adapter.execute_mutation(Insert(Customer, values={"username": "test"}))


@pytest.mark.asyncio
async def test_conformance_mysql_adapter_provisions_and_drops_database(monkeypatch):
    events = []

    class Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

        async def execute(self, sql):
            events.append(sql)

    class Connection:
        def cursor(self):
            return Cursor()

    class Pool:
        async def acquire(self):
            return Connection()

        def release(self, conn):
            events.append("release")

        def close(self):
            events.append("close")

        async def wait_closed(self):
            events.append("wait_closed")

    pool = Pool()

    async def make_pool(config, *, connect_timeout=None):
        return pool

    monkeypatch.setattr(_conformance, "_mysql_admin_pool", make_pool)
    adapter = _conformance._ConformanceMySQLAdapter(
        {"database": "renus_test_123", "host": "localhost"}
    )

    async def base_connect():
        events.append("connect")
        adapter._mysql_db = object()

    async def base_disconnect():
        adapter._mysql_db = None
        events.append("disconnect")

    monkeypatch.setattr(MySQLAdapter, "connect", lambda self: base_connect())
    monkeypatch.setattr(MySQLAdapter, "disconnect", lambda self: base_disconnect())

    await adapter.connect()
    assert events[0] == "CREATE DATABASE IF NOT EXISTS `renus_test_123`"
    assert events[1] == "release"
    assert events[-1] == "connect"

    await _conformance._drop_mysql_database(adapter)
    assert "DROP DATABASE IF EXISTS `renus_test_123`" in events
    assert events[-3:] == ["release", "close", "wait_closed"]

    await adapter.disconnect()
    assert events[-1] == "disconnect"


def test_mysql_readiness_probe_requires_create_and_drop_privileges(monkeypatch):
    statements = []

    class Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

        async def execute(self, sql):
            statements.append(sql)
            if sql.startswith("CREATE DATABASE"):
                raise PermissionError("CREATE DATABASE denied")

    class Connection:
        def cursor(self):
            return Cursor()

    class Pool:
        async def acquire(self):
            return Connection()

        def release(self, conn):
            pass

        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def make_pool(config, *, connect_timeout=None):
        return Pool()

    monkeypatch.setattr(_conformance, "_mysql_admin_pool", make_pool)

    assert _conformance._mysql_ready() is False
    assert len(statements) == 1
    assert statements[0].startswith("CREATE DATABASE `renus_conf_")


def test_mysql_database_identifier_rejects_sql_fragments():
    assert _conformance._mysql_identifier("safe_db_1") == "`safe_db_1`"
    with pytest.raises(ValueError):
        _conformance._mysql_identifier("unsafe`; DROP DATABASE mysql; --")

