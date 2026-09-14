from __future__ import annotations

import pytest

from renus.db import (
    Avg,
    Count,
    Database,
    DatabaseError,
    DatabaseField,
    DuplicateKeyError,
    Embedded,
    Field,
    Insert,
    Max,
    Min,
    MutationResult,
    PortabilityKind,
    ReModel,
    Repository,
    SQLiteAdapter,
    Sum,
    UnsupportedOperationError,
    Upsert,
)
from renus.db.sql import (
    SQLCompiled,
    SQLCompiler,
    SQLMutationCompiler
)
from renus.db.sqlite.dialect import  SQLiteDialect

from tests.db import _native_helpers as nh

class GeoAddress(ReModel):
    street: str
    city: str

class Employee(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str = Field(database=DatabaseField(unique=True))
    department: str = Field(database=DatabaseField(indexed=True))
    age: int
    salary: float
    active: bool = True
    address: GeoAddress = Embedded(GeoAddress)

    class Meta:
        timestamps = True
        soft_delete = True

class Project(ReModel):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    code: str = Field(database=DatabaseField(unique=True))
    budget: float = 0.0

def test_sqlite_dialect_quoting_and_placeholders():
    dialect = SQLiteDialect()
    assert dialect.quote("users") == '"users"'
    assert dialect.quote('user"data') == '"user""data"'
    assert dialect.placeholder == "?"
    assert dialect.placeholders(3) == "?, ?, ?"
    assert dialect.supports_returning is True

def test_sqlite_compiler_select_query():
    dialect = SQLiteDialect()
    compiler = SQLCompiler(dialect)

    query_ast = (
        Repository(SQLiteAdapter(), Employee)
        .query((Employee.age >= 21) & (Employee.active == True))
        .order_by(Employee.salary.desc())
        .limit(10)
        .offset(20)
        .ast
    )

    compiled = compiler.compile(query_ast)
    assert isinstance(compiled, SQLCompiled)
    assert 'SELECT * FROM "employees"' in compiled.sql
    assert '"deleted_at" IS NULL' in compiled.sql
    assert '"age" >= ?' in compiled.sql
    assert '"active" = ?' in compiled.sql
    assert 'ORDER BY "salary" DESC' in compiled.sql
    assert "LIMIT 10 OFFSET 20" in compiled.sql

    assert compiled.params == (21, True)

def test_sqlite_mutation_compiler_upsert():
    dialect = SQLiteDialect()
    mut_compiler = SQLMutationCompiler(dialect)

    upsert_ast = Upsert(
        Project,
        conflict_target=("code",),
        create_values={"code": "PRJ-1", "budget": 1000.0},
        update_values={"budget": 2000.0},
    )

    compiled = mut_compiler.compile(upsert_ast)
    assert "INSERT INTO" in compiled.sql
    assert "ON CONFLICT (" in compiled.sql
    assert "DO UPDATE SET" in compiled.sql
    assert compiled.params == ("PRJ-1", 1000.0, 2000.0)

@pytest.mark.asyncio
async def test_sqlite_adapter_lifecycle_and_capabilities():
    adapter = SQLiteAdapter({"database": ":memory:"})
    assert adapter.nested_documents is False

    assert await adapter.health_check() is False
    await adapter.connect()
    assert await adapter.health_check() is True
    await adapter.disconnect()
    assert await adapter.health_check() is False

@pytest.mark.asyncio
async def test_sqlite_create_schema_and_mutations():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()
    await adapter.create_schema([Employee, Project])

    res = await adapter.execute_mutation(
        Insert(Project, values={"code": "ALPHA", "budget": 50000.0})
    )
    assert isinstance(res, MutationResult)
    assert res.rows_affected == 1
    assert res.last_id == 1

    rows = await adapter.execute_query(
        Repository(adapter, Project).query(Project.code == "ALPHA").ast
    )
    assert len(rows) == 1
    assert rows[0]["code"] == "ALPHA"
    assert rows[0]["budget"] == 50000.0

    await adapter.disconnect()

@pytest.mark.asyncio
async def test_sqlite_transaction_commit():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()
    await adapter.create_schema([Project])

    async for tx in adapter.transaction_factory():
        async with tx:
            await adapter.execute_mutation(
                Insert(Project, values={"code": "TX-1", "budget": 100.0})
            )
            await tx.commit()

    rows = await adapter.execute_query(
        Repository(adapter, Project).query(Project.code == "TX-1").ast
    )
    assert len(rows) == 1
    await adapter.disconnect()

@pytest.mark.asyncio
async def test_sqlite_transaction_rollback():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()
    await adapter.create_schema([Project])

    async for tx in adapter.transaction_factory():
        async with tx:
            await adapter.execute_mutation(
                Insert(Project, values={"code": "TX-ROLLBACK", "budget": 100.0})
            )
            await tx.rollback()

    rows = await adapter.execute_query(
        Repository(adapter, Project).query(Project.code == "TX-ROLLBACK").ast
    )
    assert len(rows) == 0
    await adapter.disconnect()

@pytest.mark.asyncio
async def test_sqlite_duplicate_key_error_translation():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()
    await adapter.create_schema([Project])

    await adapter.execute_mutation(Insert(Project, values={"code": "UNIQUE-1", "budget": 100.0}))

    with pytest.raises(DuplicateKeyError):
        await adapter.execute_mutation(Insert(Project, values={"code": "UNIQUE-1", "budget": 200.0}))

    await adapter.disconnect()

@pytest.mark.asyncio
async def test_sqlite_database_error_translation():
    adapter = SQLiteAdapter({"database": ":memory:"})
    await adapter.connect()

    with pytest.raises(DatabaseError):
        await adapter.execute_query(SQLCompiled('SELECT * FROM "non_existent_table";'))

    await adapter.disconnect()

@pytest.mark.asyncio
async def test_sqlite_end_to_end_repository_operations():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Employee, Project])

    emp_repo = db.repository(Employee)
    prj_repo = db.repository(Project)

    emp = await emp_repo.create(
        Employee(
            name="Alice",
            department="Engineering",
            age=30,
            salary=90000.0,
            address=GeoAddress(street="100 Tech Blvd", city="San Francisco"),
        )
    )
    assert emp.id == 1
    assert emp.is_persisted is True

    p1 = Project(code="PRJ-A", budget=10000.0)
    p2 = Project(code="PRJ-B", budget=20000.0)
    created_prjs = await prj_repo.create_many([p1, p2])
    assert len(created_prjs) == 2
    assert p1.id is not None
    assert p2.id is not None

    q = (
        emp_repo.query(Employee.age >= 25)
        .order_by(Employee.name.asc())
        .limit(10)
    )
    results = await q.all()
    assert len(results) == 1
    assert results[0].name == "Alice"

    first_res = await q.first()
    assert first_res is not None
    assert first_res.name == "Alice"

    assert await emp_repo.count(Employee.department == "Engineering") == 1
    assert await emp_repo.exists(Employee.name == "Alice") is True
    assert await emp_repo.exists(Employee.name == "Unknown") is False

    agg_q = (
        prj_repo.query()
        .aggregate(
            total_budget=Sum(Project.budget),
            avg_budget=Avg(Project.budget),
            min_budget=Min(Project.budget),
            max_budget=Max(Project.budget),
            count_prjs=Count(Project.id),
        )
    )
    agg_results = await agg_q.all()
    assert len(agg_results) == 1
    row = agg_results[0]
    assert row["total_budget"] == 30000.0
    assert row["avg_budget"] == 15000.0
    assert row["count_prjs"] == 2

    emp.salary = 95000.0
    assert emp.is_dirty is True
    await emp_repo.save(emp)
    assert emp.is_dirty is False

    refetched = await emp_repo.query(Employee.name == "Alice").first()
    assert refetched is not None
    assert refetched.salary == 95000.0

    updated_rows = await emp_repo.update(Employee.id == 1, values={"department": "R&D"})
    assert updated_rows == 1

    del_rows = await emp_repo.delete(emp)
    assert del_rows == 1
    assert emp.is_deleted is True

    assert await emp_repo.count() == 0

    assert await emp_repo.query().with_deleted().count() == 1

    assert await emp_repo.query().only_deleted().count() == 1

    up_rows = await prj_repo.upsert(
        conflict_target=("code",),
        create_values={"code": "PRJ-A", "budget": 15000.0},
        update_values={"budget": 18000.0},
    )
    assert up_rows == 1

    prj_updated = await prj_repo.query(Project.code == "PRJ-A").first()
    assert prj_updated is not None
    assert prj_updated.budget == 18000.0

    async with db.unit_of_work() as uow:
        p_uow = uow.repository(Project)
        await p_uow.create(Project(code="UOW-PRJ", budget=5000.0))
        await uow.commit()

    assert await prj_repo.exists(Project.code == "UOW-PRJ") is True

    await db.disconnect()

@pytest.mark.asyncio
async def test_sqlite_raw_sql_via_native_connection():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()

    conn = adapter._sqlite_db
    pragma_res = [dict(r) for r in conn.execute("PRAGMA foreign_keys;").fetchall()]
    assert len(pragma_res) == 1
    assert pragma_res[0]["foreign_keys"] == 1

    conn.execute("VACUUM;")

    await db.disconnect()

@pytest.mark.asyncio
async def test_native_physical_schema_and_stored_rows():
    adapter = SQLiteAdapter({"database": ":memory:"})
    db = Database(adapter)
    await db.connect()
    await db.create_schema([Employee, Project])

    conn = db.adapter("primary")._sqlite_db

    def raw(sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    cols = raw('PRAGMA table_info("employees");')
    names = {c["name"]: c["type"] for c in cols}
    assert names["id"] == "INTEGER"
    assert names["name"] == "TEXT"
    assert names["salary"] == "REAL"
    assert "deleted_at" in names

    indexes = raw('PRAGMA index_list("employees");')
    assert any(i["unique"] == 1 for i in indexes)

    sub_tables = raw(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ? ESCAPE '\\';",
        ("employees\\_address",),
    )
    assert len(sub_tables) == 1

    emp_repo = db.repository(Employee)
    await emp_repo.create(
        Employee(
            name="Zoe",
            department="Eng",
            age=28,
            salary=92000.0,
            address=GeoAddress(street="1 Main", city="Oslo"),
        )
    )

    emp = raw('SELECT * FROM "employees";')[0]
    assert emp["name"] == "Zoe"
    assert emp["salary"] == 92000.0
    assert emp["active"] == 1
    assert "address" not in emp

    addr = raw('SELECT * FROM "employees_address";')[0]
    assert addr["parent_id"] == emp["id"]
    assert addr["street"] == "1 Main"
    assert addr["city"] == "Oslo"

    await db.disconnect()

class NativeWare(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    sku: str
    qty: int
    embedded: GeoAddress = Embedded(GeoAddress)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", nh.DUAL_BACKENDS)
async def test_native_dual_backend_persistence(kind):
    db = await nh.connect_schema(kind, [NativeWare])
    try:
        repo = db.repository(NativeWare)
        await repo.create(
            NativeWare(id="w1", sku="SKU-1", qty=5, embedded=GeoAddress(street="Main", city="Oslo"))
        )

        rows = await nh.native_all(db, "nativewares")
        assert len(rows) == 1
        assert rows[0]["sku"] == "SKU-1"
        assert rows[0]["qty"] == 5

        (loaded,) = await repo.query().include(NativeWare.embedded).all()
        assert loaded.embedded.street == "Main"
        assert loaded.embedded.city == "Oslo"
    finally:
        await nh.cleanup(db)
