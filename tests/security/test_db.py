from __future__ import annotations

import pytest
import pytest_asyncio

from renus.db import (
    Aggregate,
    Database,
    DatabaseError,
    DatabaseField,
    DuplicateKeyError,
    Field,
    HavingCondition,
    Lifecycle,
    Model,
    Operator,
    Path as QPath,
    Repository,
    SQLiteAdapter,
    ConnectionError,
    ValidationError,
)
from renus.db.migrations import Column, MigrationChecksumError
from renus.db.mongodb import MongoDBAdapter
from renus.db.mongodb.compiler import MongoCompiler
from renus.db.mongodb.dialect import MongoDialect
from renus.db.serialization import sanitize_params, to_dict, to_json
from renus.db.sql import SQLCompiler, SQLMutationCompiler
from renus.db.sqlite.dialect import SQLiteDialect

# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


class Address(Model):
    city:str
    
class User(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str = Field(database=DatabaseField(unique=True))
    email: str = ""
    age: int = 0
    address:Address|None=None
    
    class Meta:
        timestamps = True
        soft_delete = True


class SensitiveUser(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    username: str = ""
    password: str = Field(sensitive=True, default="")

    class Meta:
        timestamps = True
        soft_delete = True


class HostileTable(Model):
    """Model whose table name contains a quote/DDL payload.

    Realistic only via indirect naming (tenant-prefixed tables, config-driven
    names); used here to pin the identifier-quoting contract.
    """

    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    evil: str = ""

    class Meta:
        table = 'tab"); DROP TABLE users;--'


INJECTION_PAYLOAD = "x'; DROP TABLE users;--"
HOSTILE_COL = 'col"); DROP TABLE users;--'


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sqlite_db():
    db = Database(SQLiteAdapter({"database": ":memory:"}))
    await db.connect()
    await db.create_schema([User, SensitiveUser])
    yield db
    await db.disconnect()


@pytest.fixture
def compiler() -> SQLCompiler:
    return SQLCompiler(SQLiteDialect())


def _repo(db: Database) -> Repository:
    return db.repository(User)


# ==========================================================================
# A. LIVE VULNERABILITY DEMONSTRATIONS (pass today = the flaw is present)
# ==========================================================================


# ==========================================================================
# B. VERIFIED-SECURE BEHAVIORS (must keep working)
# ==========================================================================


class TestAggregateFunctionNameAllowlist:
    """``SQLCompiler`` interpolates ``agg.function`` into SQL, so only the
    allowlisted aggregate names (count/sum/avg/min/max) may be rendered.
    Regression test for the historical function-name SQL injection.
    """

    def test_hostile_function_name_is_rejected(self, compiler):
        ast = (
            Repository(SQLiteAdapter(), User)
            .query()
            .aggregate(
                Aggregate(function="count(*) FROM users; --", path=None, alias="cnt")
            )
            .ast
        )
        with pytest.raises(ValueError, match="Unsupported aggregate function"):
            compiler.compile(ast)

    def test_having_path_rejects_hostile_function_name(self, compiler):
        agg = Aggregate(function="count(*) FROM users; --", path=None, alias="cnt")
        ast = (
            Repository(SQLiteAdapter(), User)
            .query()
            .having(HavingCondition(Operator.GT, agg, 1))
            .ast
        )
        with pytest.raises(ValueError, match="Unsupported aggregate function"):
            compiler.compile(ast)

    def test_allowlisted_names_still_compile(self, compiler):
        for fn in ("count", "sum", "avg", "min", "max", "COUNT", "Max"):
            ast = (
                Repository(SQLiteAdapter(), User)
                .query()
                .aggregate(Aggregate(function=fn, path=User.age, alias=f"a_{fn}"))
                .ast
            )
            compiled = compiler.compile(ast)
            assert f"{fn.upper()}(" in compiled.sql

    def _mongo_ast(self, function: str, alias: str = "cnt"):
        return (
            Repository(MongoDBAdapter(), User)
            .query()
            .aggregate(Aggregate(function=function, path=User.age, alias=alias))
            .ast
        )

    def test_mongo_hostile_function_name_is_rejected(self):
        compiler = MongoCompiler()
        with pytest.raises(ValueError, match="Unsupported aggregate function"):
            compiler.compile_query(self._mongo_ast("count(*) FROM users; --"))

    def test_mongo_allowlisted_names_still_compile(self):
        compiler = MongoCompiler()

        # count over a field path (no path would bypass the operator map).
        pipeline = compiler.compile_query(self._mongo_ast("count")).pipeline
        assert pipeline[-2]["$group"]["cnt"] == {"$sum": 1}

        for fn, mongo_op in (
            ("sum", "$sum"),
            ("avg", "$avg"),
            ("min", "$min"),
            ("max", "$max"),
        ):
            pipeline = compiler.compile_query(
                self._mongo_ast(fn, alias=f"a_{fn}")
            ).pipeline
            assert pipeline[-2]["$group"][f"a_{fn}"] == {mongo_op: "$age"}

        # Case-insensitive, matching the SQL compiler's behavior.
        pipeline = compiler.compile_query(self._mongo_ast("COUNT")).pipeline
        assert pipeline[-2]["$group"]["cnt"] == {"$sum": 1}


class TestModelInitMassAssignment:
    """``Model.__init__`` must only accept declared fields (plus relationship
    names, which row hydration legitimately carries). Unknown keys — including
    framework internals like ``_db_state`` — are rejected as validation
    errors, so building a model from request input cannot inject attributes.

    Regression tests for the historical mass-assignment flaw. Note:
    ``is_deleted`` on soft-delete models is a *declared* field (the documented
    soft-delete API), so setting it explicitly remains supported by design.
    """

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(ValidationError) as exc:
            User({"name": "a", "email": "b", "is_admin": True})
        assert "Unknown field 'is_admin'" in str(exc.value)

    def test_internal_lifecycle_state_injection_is_rejected(self):
        with pytest.raises(ValidationError, match="Unknown field '_db_state'"):
            User({"name": "a", "email": "b", "_db_state": Lifecycle.PERSISTED})

    def test_rejected_keys_cannot_flip_persistence_state(self):
        # Even mixing valid and invalid keys, the model is never constructed.
        with pytest.raises(ValidationError):
            User({"name": "a", "email": "b", "_db_state": Lifecycle.PERSISTED})

    def test_non_soft_delete_model_rejects_is_deleted(self):
        class Plain(Model):
            id: int = Field(database=DatabaseField(primary_key=True, generated=True))
            name: str = ""

        with pytest.raises(ValidationError, match="Unknown field 'is_deleted'"):
            Plain({"name": "a", "is_deleted": True})

    def test_nested_rejects(self):

        with pytest.raises(ValidationError, match="Unknown field 'street'"):
            User({"name": "a", "email": "b", "address": {"city":"a","street":"b"}})

    def test_declared_fields_and_relationships_still_accepted(self):
        user = User({"name": "a", "email": "b"})
        assert user.name == "a"
        assert user.is_new() is True


# ==========================================================================
# B. VERIFIED-SECURE BEHAVIORS (must keep working)
# ==========================================================================


class TestValueParameterization:
    """Values must always travel as bound parameters, never concatenated."""

    def test_hostile_values_stay_out_of_compiled_sql(self, compiler):
        conditions = (
            User.name == INJECTION_PAYLOAD,
            User.name != INJECTION_PAYLOAD,
            User.email.like(f"%{INJECTION_PAYLOAD}%"),
            User.email.regex("(a+)+$"),
            User.name.in_([INJECTION_PAYLOAD, "' OR '1'='1"]),
            User.name.not_in([INJECTION_PAYLOAD]),
            User.age.between(1, 2),
            User.name == {"$ne": None},  # dict values become data, not SQL
        )
        for cond in conditions:
            compiled = compiler.compile(
                Repository(SQLiteAdapter(), User).query(cond).ast
            )
            assert INJECTION_PAYLOAD not in compiled.sql, cond
            assert "' OR '1'='1" not in compiled.sql, cond
            assert "$ne" not in compiled.sql, cond

    @pytest.mark.asyncio
    async def test_injection_payload_matches_nothing_and_leaves_db_intact(
        self, sqlite_db
    ):
        users = _repo(sqlite_db)
        await users.create(User({"name": "alice", "email": "a@x.com"}))
        await users.create(User({"name": "bob", "email": "b@x.com"}))

        for value in (
            "alice' OR '1'='1",
            f"alice'; DROP TABLE users;--",
            "alice' UNION SELECT 1,2,3--",
        ):
            rows = await users.query(User.name == value).all()
            assert rows == []

        # The table is still alive and intact.
        assert await users.query().count() == 2

    @pytest.mark.asyncio
    async def test_like_wildcards_are_bound_data(self, sqlite_db, compiler):
        compiled = compiler.compile(
            Repository(SQLiteAdapter(), User).query(User.name.like("%'--")).ast
        )
        assert "LIKE ?" in compiled.sql

        users = _repo(sqlite_db)
        await users.create(User({"name": "alice", "email": "a@x.com"}))
        rows = await users.query(User.name.like("%")).all()
        assert len(rows) == 1  # executes; % is a real wildcard, not SQL

    @pytest.mark.asyncio
    async def test_null_bytes_and_unicode_are_plain_data(self, sqlite_db):
        users = _repo(sqlite_db)
        await users.create(User({"name": "alisé", "email": "a@x.com"}))

        assert await users.query(User.name == "alisé\x00'; --").all() == []
        assert (await users.query(User.name == "alisé").first()).name == "alisé"

    def test_limit_offset_reject_non_numeric_input(self):
        with pytest.raises(ValueError):
            Repository(SQLiteAdapter(), User).query().limit("5; DROP TABLE users")
        with pytest.raises(ValueError):
            Repository(SQLiteAdapter(), User).query().offset("1; DROP TABLE users")


class TestIdentifierQuoting:
    """Identifiers are escaped by doubling embedded double quotes."""

    def test_quote_contract(self):
        dialect = SQLiteDialect()
        assert dialect.quote("users") == '"users"'
        assert dialect.quote('user"data') == '"user""data"'
        assert dialect.quote(HOSTILE_COL) == '"col""); DROP TABLE users;--"'

    def test_hostile_table_name_is_escaped_in_queries(self, compiler):
        compiled = compiler.compile(
            Repository(SQLiteAdapter(), HostileTable).query(HostileTable.evil == "v").ast
        )
        assert '"tab""); DROP TABLE users;--"' in compiled.sql

    def test_hostile_column_name_in_update_values_is_escaped(self):
        mc = SQLMutationCompiler(SQLiteDialect())
        compiled = mc.compile(
            __import__("renus.db.mutation.ast", fromlist=["Update"]).Update(
                HostileTable, values={HOSTILE_COL: "v"}
            )
        )
        assert '"tab""); DROP TABLE users;--"' in compiled.sql
        assert '"col""); DROP TABLE users;--"' in compiled.sql

    @pytest.mark.asyncio
    async def test_hostile_named_schema_round_trips(self):
        db = Database(SQLiteAdapter({"database": ":memory:"}))
        await db.connect()
        try:
            await db.create_schema([HostileTable])
            repo = db.repository(HostileTable)
            created = await repo.create(HostileTable({"evil": "payload"}))
            rows = await repo.query(HostileTable.evil == "payload").all()
            assert len(rows) == 1
            assert rows[0].id == created.id
        finally:
            await db.disconnect()

    @pytest.mark.asyncio
    async def test_unknown_ordering_path_cannot_inject(self, sqlite_db):
        users = _repo(sqlite_db)
        await users.create(User({"name": "alice", "email": "a@x.com"}))

        hostile = QPath(User, ('name; DROP TABLE users--',))
        compiled_sql = SQLCompiler(SQLiteDialect()).compile(
            users.query().order_by(hostile).ast
        ).sql
        assert '"name; DROP TABLE users--"' in compiled_sql  # quoted, not raw

        # Execution is safe. (SQLite resolves an unknown double-quoted
        # identifier as a string literal — its documented misfeature — so
        # this does not raise; the point is that the payload never breaks
        # out of the identifier position.)
        rows = await users.query().order_by(hostile).all()
        assert len(rows) == 1

        # DB intact.
        assert await users.query().count() == 1


class TestMongoNoSQLInjection:
    """BSON value encoding must refuse ``$``-prefixed operator smuggling."""

    def test_dollar_prefixed_keys_are_rejected(self):
        dialect = MongoDialect()
        with pytest.raises(DatabaseError):
            dialect.encode_value({"$ne": None})
        with pytest.raises(DatabaseError):
            dialect.encode_value({"nested": {"$where": "1"}})

    def test_operator_smuggling_via_eq_value_is_rejected(self):
        compiler = MongoCompiler()
        ast = Repository(MongoDBAdapter(), User).query(
            User.name == {"$ne": None}
        ).ast
        with pytest.raises(DatabaseError):
            compiler.compile_query(ast)


class TestSensitiveDataHandling:
    @pytest.mark.asyncio
    async def test_attribute_read_masks_sensitive_value(self):
        user = SensitiveUser({"username": "u", "password": "sup3r-secret"})

        assert getattr(user, "password") == "***"
        assert user.get_sensitive("password") == "sup3r-secret"

    @pytest.mark.asyncio
    async def test_serialization_paths_never_leak_the_secret(self):
        user = SensitiveUser({"username": "u", "password": "sup3r-secret"})

        assert "password" not in dict(user)
        assert "password" not in to_dict(user)
        assert "sup3r-secret" not in to_json(user)
        assert "sup3r-secret" not in repr(user)
        assert sanitize_params(user)["password"] == "***"

    @pytest.mark.asyncio
    async def test_sensitive_value_persists_but_is_masked_on_read(self, sqlite_db):
        repo = sqlite_db.repository(SensitiveUser)
        created = await repo.create(
            SensitiveUser({"username": "u", "password": "sup3r-secret"})
        )

        fetched = await repo.query(SensitiveUser.username == "u").first()
        assert fetched is not None
        assert fetched.get_sensitive("password") == "sup3r-secret"
        assert fetched.password == "***"

    def test_include_sensitive_is_explicit_opt_in(self):
        user = SensitiveUser({"username": "u", "password": "sup3r-secret"})

        assert to_dict(user, include_sensitive=True)["password"] == "sup3r-secret"


class TestSoftDeleteIsolation:
    @pytest.mark.asyncio
    async def test_deleted_rows_are_invisible_by_default(self, sqlite_db):
        users = _repo(sqlite_db)
        await users.create(User({"name": "victim", "email": "v@x.com"}))
        await users.create(User({"name": "other", "email": "o@x.com"}))

        await users.delete(User.name == "victim")

        assert [u.name for u in await users.query().all()] == ["other"]
        assert [u.name for u in await users.query().only_deleted().all()] == [
            "victim"
        ]
        assert len(await users.query().with_deleted().all()) == 2

        n = await users.hard_delete(User.name == "victim")
        assert n == 1
        assert await users.query().with_deleted().count() == 1


class TestErrorMappingAndConfigBoundary:
    @pytest.mark.asyncio
    async def test_duplicate_key_raises_typed_error(self, sqlite_db):
        users = _repo(sqlite_db)
        await users.create(User({"name": "dup", "email": "d@x.com"}))

        with pytest.raises(DuplicateKeyError):
            await users.create(User({"name": "dup", "email": "d2@x.com"}))

        # Failure left the store consistent.
        assert await users.query().count() == 1

    @pytest.mark.asyncio
    async def test_hostile_pragma_config_cannot_chain_statements(self):
        adapter = SQLiteAdapter(
            {"database": ":memory:", "journal_mode": "wal; DROP TABLE users"}
        )
        with pytest.raises(ConnectionError):
            await adapter.connect()


class TestMigrationIntegrity:
    @pytest.mark.asyncio
    async def test_tampered_applied_migration_is_rejected(self, tmp_path):
        db = Database(SQLiteAdapter({"database": ":memory:"}))
        await db.connect()
        try:
            mgr = db.migration_manager(path=str(tmp_path))
            path = mgr.create("add notes")
            await mgr.upgrade()
            assert await mgr.check()

            # Edit an already-applied migration → checksum mismatch.
            path.write_text(path.read_text(encoding="utf-8") + "\n# tampered")

            with pytest.raises(MigrationChecksumError):
                await mgr.upgrade()
            with pytest.raises(MigrationChecksumError):
                await mgr.check()
        finally:
            await db.disconnect()
