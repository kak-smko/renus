"""Conformance suite: the standard operations every adapter must support.

Each test here runs against every registered adapter driver (see
``tests/db/_conformance.py``). A new backend joins the suite by registering an
``AdapterDriver``; if it passes this whole module it is correctly implemented
for the standard Renus database operations.

Run with::

    venv/bin/python -m pytest tests/db/test_adapter_conformance.py
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from bson.objectid import ObjectId
import pytest
from renus.datastructures.id import ID
from renus.config import Config
from renus.db import (
    Avg,
    Column,
    Count,
    Database,
    DatabaseField,
    DuplicateKeyError,
    Field,
    Include,
    IntegrityError,
    LoadingStrategy,
    ValidationError,
    ManyToMany,
    ManyToOne,
    Max,
    MigrationChecksumError,
    MigrationManager,
    Min,
    OneToMany,
    Q,
    OneToOne,
    ReferentialAction,
    RelationshipKind,
    Model,
    SaveAction,
    Sum,

)
from renus.datastructures import ID
from renus.db.query.ast import Path, QueryAST
from renus.db.validation import MaxLen
from tests.db.deep_relation_models import DEEP_RELATION_FAMILIES
from tests.db.deep_embedded_models import (
    DeepEmbedded1,
    DeepEmbedded2,
    DeepEmbedded3,
    DeepEmbedded4,
    DeepEmbedded5,
    DeepEmbedded6,
    DeepEmbedded7,
    DeepMany1,
    DeepMany2,
    DeepMany3,
    DeepMany4,
    DeepMany5,
    DeepMany6,
    DeepMany7,
    DeepRoot,
)
from renus.db.repository.relationships import _junction_columns
from tests.db._conformance import (
    Citizen,
    Contact,
    Dept,
    Version,
    Employee,
    Item,
    Passport,
    Post,
    Profile,
    Role,
    SoftUser,
    Tag,
    User,
    cleanup,
    conformance_tests,
    database_for,
    adapter_for,
)

ADAPTERS = conformance_tests()


def _utc_timestamp(value: datetime) -> datetime:
    """Normalize adapter timestamps for portable ordering assertions."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _u(uid: str, username: str, **kw):
    defaults = {"name": None, "age": 0, "active": True}
    defaults.update(kw)
    return User(id=uid, username=username, **defaults)


def _p(pid: str, title: str, user_id: str = ""):
    return Post(id=pid, title=title, user_id=user_id)


class NestedDepartment(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str


class NestedEmployee(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    company_id: str = ""
    department_id: str = ""
    department: NestedDepartment = ManyToOne(
        NestedDepartment,
        foreign_key="department_id",
        loading=LoadingStrategy.LAZY,
    )


class NestedCompany(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    employees: list[NestedEmployee] = OneToMany(
        NestedEmployee,
        foreign_key="company_id",
        loading=LoadingStrategy.LAZY,
    )


class StrategyChild(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    joined_parent_id: str = ""
    lazy_parent_id: str = ""
    label: str


class JoinedParent(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    children: list[StrategyChild] = OneToMany(
        StrategyChild,
        foreign_key="joined_parent_id",
        loading=LoadingStrategy.JOINED,
    )


class LazyParent(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    children: list[StrategyChild] = OneToMany(
        StrategyChild,
        foreign_key="lazy_parent_id",
        loading=LoadingStrategy.LAZY,
    )


class UnannotatedEmbeddedChild(Model):
    id: int
    name: str


class UnannotatedEmbeddedOwner(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    data: list[UnannotatedEmbeddedChild] = Field(default_factory=list)


_row_count_models: dict[str, type] = {}


_row_count_models: dict[str, type] = {}


def _row_count_model(table: str) -> type:
    """Return a lightweight model bound to an existing table/collection."""
    model = _row_count_models.get(table)
    if model is None:
        meta = type("Meta", (), {"table": table})
        model = type(f"_RowCount_{table}", (Model,), {"Meta": meta})
        _row_count_models[table] = model
    return model


async def _row_counts(db, *tables: str) -> dict[str, int]:
    """Return the number of rows stored in each table/collection."""
    return {t: await db.repository(_row_count_model(t)).count() for t in tables}


async def _table_names(db) -> set[str]:
    """Return lower-cased table/collection names on the database."""
    return {t.lower() for t in await db.tables()}


_known_mig_models: dict[tuple[str, tuple[str, ...]], type] = {}


def _mig_model(table: str, fields: dict[str, type]) -> type:
    """Build a Model bound to a migration-created table.

    The model has a string ``id`` primary key plus the requested fields, and
    is cached so repeated builds with the same shape share one class.
    """
    key = (table, tuple(sorted(fields)))
    cached = _known_mig_models.get(key)
    if cached is not None:
        return cached
    annotations: dict[str, type] = {"id": str}
    attrs: dict[str, Any] = {"id": Field(database=DatabaseField(primary_key=True))}
    for name, typ in fields.items():
        annotations[name] = typ
        if typ is int:
            attrs[name] = 0
        elif typ is float:
            attrs[name] = 0.0
        else:
            attrs[name] = ""
    meta = type("Meta", (), {"table": table})
    cls = type(
        f"_M_{table}_{'_'.join(sorted(fields))}",
        (Model,),
        {"__annotations__": annotations, **attrs, "Meta": meta},
    )
    _known_mig_models[key] = cls
    return cls


def _o2o_pair(
    name,
    *,
    on_save,
    on_delete,
    on_update,
    fk_default=None,
) -> tuple[type, type, str]:
    """Build a one-to-one owner/child model pair for action testing."""
    fk = f"{name.lower()}_id"
    child_cls = type(
        f"{name}Detail",
        (Model,),
        {
            "__annotations__": {"id": str, fk: (str | None), "label": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: fk_default,
            "label": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str, "detail": child_cls},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
            "detail": OneToOne(
                child_cls,
                foreign_key=fk,
                on_save=on_save,
                on_delete=on_delete,
                on_update=on_update,
            ),
        },
    )
    return owner_cls, child_cls, fk


def _o2m_pair(
    name,
    *,
    on_save,
    on_delete,
    on_update,
    fk_default=None,
) -> tuple[type, type, str]:
    """Build a one-to-many owner/child model pair for action testing."""
    fk = f"{name.lower()}_id"
    child_cls = type(
        f"{name}Child",
        (Model,),
        {
            "__annotations__": {"id": str, fk: (str | None), "label": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: fk_default,
            "label": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str, "children": list[child_cls]},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
            "children": OneToMany(
                child_cls,
                foreign_key=fk,
                on_save=on_save,
                on_delete=on_delete,
                on_update=on_update,
            ),
        },
    )
    return owner_cls, child_cls, fk


def _m2o_pair(
    name,
    *,
    on_save,
) -> tuple[type, type, str]:
    """Build a many-to-one holder/parent model pair for action testing.

    The holder carries the foreign key and the ``ManyToOne`` relationship;
    many-to-one only supports ``on_save`` (delete/update are always no action).
    """
    fk = f"{name.lower()}_id"
    parent_cls = type(
        f"{name}Parent",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
        },
    )
    holder_cls = type(
        f"{name}Item",
        (Model,),
        {
            "__annotations__": {
                "id": str,
                fk: (str | None),
                "label": str,
                "parent": parent_cls,
            },
            "id": Field(database=DatabaseField(primary_key=True)),
            fk: None,
            "label": "",
            "parent": ManyToOne(
                parent_cls,
                foreign_key=fk,
                on_save=on_save,
            ),
        },
    )
    return holder_cls, parent_cls, fk


def _mtm_pair(
    name,
    *,
    on_save,
) -> tuple[type, type, str]:
    """Build a many-to-many owner/target model pair for action testing.

    Many-to-many only supports ``on_save`` (delete/update are fixed to cascade
    and operate on the junction ``through`` table).
    """
    through = f"{name.lower()}_links"
    target_cls = type(
        f"{name}Role",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
        },
    )
    owner_cls = type(
        f"{name}Owner",
        (Model,),
        {
            "__annotations__": {"id": str, "name": str, "items": list[target_cls]},
            "id": Field(database=DatabaseField(primary_key=True)),
            "name": "",
            "items": ManyToMany(
                target_cls,
                through=through,
                on_save=on_save,
            ),
        },
    )
    return owner_cls, target_cls, through


# ---------------------------------------------------------------------------
# Lifecycle & schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_lifecycle_connect_health_disconnect(kind):
    from tests.db._conformance import adapter_for, cleanup_adapter

    adapter = adapter_for(kind)
    assert await adapter.health_check() is False
    await adapter.connect()
    assert await adapter.health_check() is True
    await cleanup_adapter(adapter)
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_schema_and_tables(kind):
    db = await database_for(kind)
    try:
        tables = await db.tables()
        names = {t.lower() for t in tables}
        assert any("users" in n for n in names), f"missing users among {names}"
    finally:
        await cleanup(db)



# ---------------------------------------------------------------------------
# Repository CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_and_read(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        user = await repo.create(
            _u(
                "u1",
                "alice",
                name="Alice",
                age=30,
                profile=Profile(city="Tehran", street="one"),
            )
        )
        assert user.id is not None
        assert user.is_persisted() is True

        fetched = await db.repository(User).where(User.username == "alice").first()
        assert fetched is not None
        assert fetched.name == "Alice"
        assert fetched.age == 30
        assert fetched.active is True
        assert fetched.id == "u1"

        fetched = await db.repository(User).where(User.profile.city == "Tehran").first()
        assert fetched is not None
        assert fetched.name == "Alice"
        assert fetched.age == 30
        assert fetched.active is True
        assert fetched.id == "u1"

        fetched = await db.repository(User).where(User.profile.city == "Fake").first()
        assert fetched is None
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_many(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        created = await repo.create_many(
            [
                _u("u1", "u1", name="One", age=20),
                _u("u2", "u2", name="Two", age=30),
                _u("u3", "u3", name="Three", age=40),
            ]
        )
        assert len(created) == 3
        assert all(u.id is not None for u in created)
        assert await repo.count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_save_insert_and_update(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        obj = _u("s1", "saved", name="First", age=5)
        await repo.save(obj)  # insert path
        assert obj.is_persisted() is True

        obj.name = "Second"
        obj.age = 6
        await repo.save(obj)  # update path
        assert obj.is_dirty() is False

        loaded = await repo.where(User.username == "saved").first()
        assert loaded is not None
        assert loaded.name == "Second"
        assert loaded.age == 6
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_update_many_rows(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("a", "a", age=10, active=True),
                _u("b", "b", age=20, active=True),
                _u("c", "c", age=30, active=False),
            ]
        )
        rows = await repo.update_many(User.active == True, values={"age": 99})
        assert rows == 2
        assert await repo.count(User.age == 99) == 2
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_update_single_row(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("su1", "su1", age=10, active=True),
                _u("su2", "su2", age=20, active=True),
            ]
        )

        rows = await repo.update(User.active == True, values={"age": 99})
        assert rows == 1
        assert (await repo.where(User.username == "su1").first()).age == 99
        assert (await repo.where(User.username == "su2").first()).age == 20
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_delete_single_row(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("sd1", "sd1", age=10, active=True),
                _u("sd2", "sd2", age=20, active=True),
            ]
        )

        rows = await repo.delete(User.active == True)
        assert rows == 1
        assert await repo.count(User.active == True) == 1

        remaining = await repo.query(User.active == True).all()
        assert {u.username for u in remaining} - {"sd1", "sd2"} == set()
        assert {u.username for u in remaining} != {"sd1", "sd2"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_delete_rows(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [_u(f"d{i}", f"d{i}", age=i, active=True) for i in range(3)]
        )
        rows = await repo.delete(User.username == "d0")
        assert rows == 1
        assert await repo.count() == 2
        assert await repo.count(User.username == "d0") == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_delete_many_rows(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("dm1", "dm1", age=10, active=True),
                _u("dm2", "dm2", age=20, active=True),
                _u("dm3", "dm3", age=30, active=False),
            ]
        )
        # ``delete_many`` removes every matching row (soft-deletes here, so they
        # leave the live count but remain visible with_deleted).
        rows = await repo.delete_many(User.active == True)
        assert rows == 2
        assert await repo.count() == 1
        assert await repo.count(User.active == True) == 0
        assert await repo.query().with_deleted().count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_limit_offset_ignored_for_update_delete(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("io1", "io1", age=10, active=True),
                _u("io2", "io2", age=20, active=True),
                _u("io3", "io3", age=30, active=False),
            ]
        )

        rows = (
            await repo.query(User.active == True).limit(1).offset(1).update({"age": 99})
        )
        assert rows == 2
        assert await repo.count(User.age == 99) == 2

        deleted = await repo.query(User.active == True).limit(1).offset(1).delete()
        assert deleted == 2
        assert await repo.count() == 1
        assert await repo.query().with_deleted().count() == 3
    finally:
        await cleanup(db)




@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_count_and_exists(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("c1", "c1", active=True),
                _u("c2", "c2", active=True),
                _u("c3", "c3", active=False),
            ]
        )
        assert await repo.count() == 3
        assert await repo.count(User.active == True) == 2
        assert await repo.exists(User.username == "c1") is True
        assert await repo.exists(User.username == "nope") is False
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_filters_and_ordering(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("bob", "bob", name="Bob", age=40, active=True),
                _u("ann", "ann", name="Ann", age=25, active=True),
                _u("cat", "cat", name="Cat", age=18, active=False),
            ]
        )

        rows = await repo.query(User.age >= 20).order_by(User.age.asc()).all()
        assert [u.username for u in rows] == ["ann", "bob"]

        first = await repo.query(User.active == True).order_by(User.age.desc()).first()
        assert first is not None
        assert first.username == "bob"

        assert len(await repo.query(User.username.in_(["bob", "cat"])).all()) == 2
        assert len(await repo.query(User.age.between(20, 45)).all()) == 2
        like = await repo.query(User.name.like("An%")).all()
        assert [u.username for u in like] == ["ann"]
        assert await repo.query(User.name.is_null()).count() == 0
        assert await repo.query(User.name.is_not_null()).count() == 3
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_conditions_and_builder_aliases(kind):
    """Exercise the remaining condition and builder features across adapters."""
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u(
                    f"cf-{i:03d}",
                    f"cf-{i:03d}",
                    name=None if i % 10 == 0 else f"team-{i % 4}",
                    age=i,
                    active=i % 2 == 0,
                )
                for i in range(120)
            ]
        )
        assert await repo.count() == 120
        assert await repo.query(User.name.is_null()).count() == 12
        assert await repo.query(User.name.is_not_null()).count() == 108

        # ``filter`` is an alias for ``where`` and Query.__call__ adds filters.
        assert await repo.query().filter(User.age >= 110).count() == 10
        first_three = await repo.query()(User.age < 3).order_by(User.age).all()
        assert [user.age for user in first_three] == [0, 1, 2]

        # Q(), &, |, and ~ must preserve logical grouping when compiled.
        active_adults = await repo.query(
            Q(User.active == True, User.age >= 100)
        ).all()
        assert [user.age for user in active_adults] == list(range(100, 120, 2))

        edge_rows = await repo.query(
            (User.age < 3) | (User.age >= 118)
        ).order_by(User.age).all()
        assert [user.age for user in edge_rows] == [0, 1, 2, 118, 119]

        not_young = await repo.query(~(User.age < 118)).order_by(User.age).all()
        assert [user.age for user in not_young] == [118, 119]

        # Exercise every scalar comparison and explicit collection/pattern
        # operator against known boundary values.
        assert await repo.query(User.age != 0).count() == 119
        assert await repo.query(User.age > 110).count() == 9
        assert await repo.query(User.age >= 110).count() == 10
        assert await repo.query(User.age < 10).count() == 10
        assert await repo.query(User.age <= 10).count() == 11
        assert await repo.query(User.age.not_in([0, 1, 2])).count() == 117
        assert await repo.query(User.username.regex(r"^cf-00[1-3]$")).count() == 3
        assert await repo.query(User.name.is_null()).count() == 12
        assert await repo.query(User.name.is_not_null()).count() == 108


        # Grouping by more than one field must retain both group keys. HAVING
        # then removes the null group while retaining the larger non-null
        # groups.
        grouped = await (
            repo.query()
            .group_by(User.active, User.name)
            .aggregate(rows=Count(User.id))
            .all()
        )
        grouped_counts = {
            (row["active"], row["name"]): row["rows"] for row in grouped
        }
        assert grouped_counts == {
            (True, None): 12,
            (True, "team-0"): 24,
            (True, "team-2"): 24,
            (False, "team-1"): 30,
            (False, "team-3"): 30,
        }

        filtered_groups = await (
            repo.query()
            .group_by(User.active, User.name)
            .aggregate(rows=Count(User.id), average_age=Avg(User.age))
            .having(Count(User.id) >= 24)
            .all()
        )
        filtered_counts = {
            (row["active"], row["name"]): row["rows"]
            for row in filtered_groups
        }
        assert filtered_counts == {
            (True, "team-0"): 24,
            (True, "team-2"): 24,
            (False, "team-1"): 30,
            (False, "team-3"): 30,
        }
        assert all(isinstance(row["average_age"], (int, float)) for row in filtered_groups)


        # Distinct aggregate forms must be computed, not merely accepted by
        # the AST. All ages are unique, while each name has four values.
        distinct_summary = await (
            repo.query()
            .aggregate(
                distinct_total=Sum(User.age, distinct=True),
                distinct_average=Avg(User.age, distinct=True),
            )
            .all()
        )
        assert distinct_summary == [{
            "distinct_total": sum(range(120)),
            "distinct_average": sum(range(120)) / 120,
        }]

        # Multiple HAVING predicates and logical HAVING composition are both
        # evaluated after grouping.
        compound_having = await (
            repo.query()
            .group_by(User.active, User.name)
            .aggregate(rows=Count(User.id), total=Sum(User.age))
            .having((Count(User.id) >= 24) & (Sum(User.age) > 1000))
            .all()
        )
        assert {
            (row["active"], row["name"]): row["rows"]
            for row in compound_having
        } == {
            (True, "team-0"): 24,
            (True, "team-2"): 24,
            (False, "team-1"): 30,
            (False, "team-3"): 30,
        }

        separate_having = await (
            repo.query()
            .group_by(User.active, User.name)
            .aggregate(rows=Count(User.id), total=Sum(User.age))
            .having(Count(User.id) >= 24, Sum(User.age) > 1000)
            .order_by(User.active.asc())
            .offset(1)
            .limit(2)
            .all()
        )
        assert len(separate_having) == 2
        assert [row["rows"] for row in separate_having] == [30, 24]

        ascing = await (
            repo.query()
            .order_by(User.name.asc(), User.age.asc())
            .all()
        )
        assert [user.age for user in ascing] == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 4, 8, 12, 16, 24, 28, 32, 36, 44, 48, 52, 56, 64, 68, 72, 76, 84, 88, 92, 96, 104, 108, 112, 116, 1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65, 69, 73, 77, 81, 85, 89, 93, 97, 101, 105, 109, 113, 117, 2, 6, 14, 18, 22, 26, 34, 38, 42, 46, 54, 58, 62, 66, 74, 78, 82, 86, 94, 98, 102, 106, 114, 118, 3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47, 51, 55, 59, 63, 67, 71, 75, 79, 83, 87, 91, 95, 99, 103, 107, 111, 115, 119]

        descing = await (
            repo.query()
            .order_by(User.name.desc(), User.age.asc())
            .all()
        )
        assert [user.age for user in descing] == [3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47, 51, 55, 59, 63, 67, 71, 75, 79, 83, 87, 91, 95, 99, 103, 107, 111, 115, 119, 2, 6, 14, 18, 22, 26, 34, 38, 42, 46, 54, 58, 62, 66, 74, 78, 82, 86, 94, 98, 102, 106, 114, 118, 1, 5, 9, 13, 17, 21, 25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65, 69, 73, 77, 81, 85, 89, 93, 97, 101, 105, 109, 113, 117, 4, 8, 12, 16, 24, 28, 32, 36, 44, 48, 52, 56, 64, 68, 72, 76, 84, 88, 92, 96, 104, 108, 112, 116, 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110]

        await repo.create(
            _u(
                "cf-nested",
                "cf-nested",
                age=120,
                profile=Profile(city="Nested", street="projection"),
            )
        )
        embedded_projection = await (
            repo.query(User.username == "cf-nested")
            .select(User.profile.city)
            .all()
        )
        assert embedded_projection == [{"city": "Nested"}]

    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_update_many(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("qu1", "qu1", age=10, active=True),
                _u("qu2", "qu2", age=20, active=True),
                _u("qu3", "qu3", age=30, active=False),
            ]
        )

        rows = await repo.query(User.active == True).update({"age": 99})
        assert rows == 2
        assert await repo.count(User.age == 99) == 2
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_delete_many(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("qd1", "qd1", age=10, active=True),
                _u("qd2", "qd2", age=20, active=True),
                _u("qd3", "qd3", age=30, active=False),
            ]
        )

        rows = await repo.query(User.active == True).delete()
        assert rows == 2
        assert await repo.count() == 1
        assert await repo.query().with_deleted().count() == 3
    finally:
        await cleanup(db)




@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_pagination(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many([_u(f"p{i:02d}", f"p{i:02d}", age=i) for i in range(5)])
        page = await repo.query().order_by(User.age.asc()).offset(1).limit(2).all()
        assert [u.username for u in page] == ["p01", "p02"]

        page1 = await repo.query().order_by(User.age.asc()).paginate(1, 2).all()
        page2 = await repo.query().order_by(User.age.asc()).paginate(2, 2).all()
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].username == "p00"
        assert page2[0].username == "p02"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_query_select_returns_dicts(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("s1", "s1", name="A", age=1),
                _u("s2", "s2", name="B", age=2),
            ]
        )
        sel = await repo.query().select(User.username).all()
        assert all(isinstance(r, dict) for r in sel)
        assert {r["username"] for r in sel} == {"s1", "s2"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_aggregations(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("g1", "g1", name="A", age=10, active=True),
                _u("g2", "g2", name="B", age=20, active=True),
                _u("g3", "g3", name="C", age=30, active=False),
            ]
        )
        row = (
            await repo.query()
            .aggregate(
                n=Count(User.id),
                total=Sum(User.age),
                avg=Avg(User.age),
                lo=Min(User.age),
                hi=Max(User.age),
            )
            .all()
        )
        assert len(row) == 1
        r = row[0]
        assert r["n"] == 3
        assert r["total"] == 60
        assert r["avg"] == 20
        assert r["lo"] == 10
        assert r["hi"] == 30

        by_active = (
            await repo.query().group_by(User.active).aggregate(n=Count(User.id)).all()
        )
        counts = {r["active"]: r["n"] for r in by_active}
        assert counts[True] == 2
        assert counts[False] == 1
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_large_query_ast_features(kind):
    """Exercise every result-shaping query feature on a substantial dataset."""
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u(
                    f"q-{i:03d}",
                    f"q-{i:03d}",
                    name=f"team-{i % 4}",
                    age=i,
                    active=i % 3 != 0,
                )
                for i in range(120)
            ]
        )
        assert await repo.count() == 120

        # Projection returns dictionaries and does not hydrate full models.
        projected = await (
            repo.query(User.age >= 100)
            .select(User.username, User.age)
            .order_by(User.age.asc())
            .all()
        )
        assert projected == [
            {"username": f"q-{i:03d}", "age": i} for i in range(100, 120)
        ]

        # DISTINCT is meaningful here because names deliberately repeat.
        distinct_names = await (
            repo.query().select(User.name).distinct().order_by(User.name.asc()).all()
        )
        assert distinct_names == [{"name": f"team-{i}"} for i in range(4)]

        distinct_active = await (
            repo.query().select(User.active).distinct().order_by(User.active.desc()).all()
        )
        assert distinct_active == [{"active": True} ,{"active": False}]

        # OFFSET and LIMIT must be applied after deterministic ordering.
        window = await (
            repo.query()
            .order_by(User.age.asc())
            .offset(17)
            .limit(13)
            .all()
        )
        assert [user.age for user in window] == list(range(17, 30))

        # A cursor starts strictly after its token and honors the ordering.
        cursor_page = await (
            repo.query()
            .order_by(User.age.asc())
            .cursor(59, field=User.age)
            .limit(10)
            .all()
        )
        assert [user.age for user in cursor_page] == list(range(60, 70))

        grouped = await (
            repo.query()
            .group_by(User.active)
            .aggregate(
                rows=Count(User.id),
                unique_names=Count(User.name, distinct=True),
                total_age=Sum(User.age),
            )
            .having(Count(User.id) > 40)
            .all()
        )
        assert grouped == [
            {"active": True, "rows": 80, "unique_names": 4, "total_age": 4800}
        ]
        grouped = await (
            repo.query()
            .group_by(User.active)
            .aggregate(
                rows=Count(User.id),
                unique_names=Count(User.name, distinct=True),
                total_age=Sum(User.age),
            )
            .all()
        )
        grouped.sort(key=lambda x: x['active'])
        assert grouped == [
             {"active": False, "rows": 40, "unique_names": 4, "total_age": 2340},
            {"active": True,  "rows": 80, "unique_names": 4, "total_age": 4800},
        ]
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_model_lifecycle_and_clean_save(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        user = _u("state-1", "state-1", name="before", age=10)

        assert user.is_new() is True
        assert user.is_persisted() is False
        assert user.is_dirty() is False
        assert user.is_deleted() is False

        await repo.create(user)
        assert user.is_new() is False
        assert user.is_persisted() is True
        assert user.is_dirty() is False
        assert user.dirty_fields() == set()
        assert user.get_dirty_changes() == {}

        mutation_calls = 0
        execute_mutation = db.adapter("primary").execute_mutation

        async def counted_mutation(compiled):
            nonlocal mutation_calls
            mutation_calls += 1
            return await execute_mutation(compiled)

        db.adapter("primary").execute_mutation = counted_mutation
        clean_result = await repo.save(user)
        assert clean_result is user
        assert mutation_calls == 0

        user.name = "after"
        user.age = 11
        assert user.is_dirty() is True
        assert user.is_persisted() is False
        assert user.dirty_fields() == {"name", "age"}
        assert user.get_dirty_changes() == {
            "name": ("before", "after"),
            "age": (10, 11),
        }

        await repo.save(user)
        assert mutation_calls == 1
        assert user.is_persisted() is True
        assert user.is_dirty() is False
        assert user.dirty_fields() == set()
        assert user.get_dirty_changes() == {}

        await repo.delete(user)
        assert user.is_deleted() is True
        assert user.is_persisted() is False
    finally:
        await cleanup(db)






@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_generated_fields_on_create_and_create_many(kind, monkeypatch):
    monkeypatch.setitem(Config._cache, "database", SimpleNamespace(ID=int))

    class GeneratedRecord(Model):
        id: ID = Field(
            database=DatabaseField(primary_key=True, generated=True, auto_inc=True)
        )
        name: str
        token: UUID = Field(default_factory=uuid4, database=DatabaseField(generated=True))

    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema([GeneratedRecord])
    try:
        repo = db.repository(GeneratedRecord)
        single = await repo.create(GeneratedRecord(name="single"))
        many = await repo.create_many(
            [GeneratedRecord(name=f"bulk-{i}") for i in range(3)]
        )
        rows = [single, *many]

        assert all(row.is_persisted() for row in rows)
        assert all(row.id is not None for row in rows)
        assert all(isinstance(row.token, UUID) for row in rows)
        id_values = {
            row.id.value if isinstance(row.id, ID) else row.id for row in rows
        }
        assert len(id_values) == 4
        assert len({row.token for row in rows}) == 4

        fetched = await repo.query().order_by(GeneratedRecord.name.asc()).all()
        assert len(fetched) == 4
        assert all(row.id is not None for row in fetched)
        assert all(isinstance(row.token, UUID) for row in fetched)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_large_mutation_conformance(kind):
    """Check mutation result contracts using 120 persisted rows."""
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        created = await repo.create(
                    _u("m-single", "m-single", name="before", age=1, active=False)
                )
        assert created.id == "m-single"
        assert created.username == "m-single"
        assert created.name == "before"

        bulk = [
            _u(
                f"m-{i:03d}",
                f"m-{i:03d}",
                name=f"bulk-{i % 5}",
                age=i,
                active=i < 80,
            )
            for i in range(120)
        ]
        returned = await repo.create_many(bulk)
        assert returned == bulk
        assert await repo.count() == 121

        # Single-row and bulk updates return affected-row counts, and the
        # persisted values are the same for every adapter.
        assert await repo.update(
            User.username == "m-single", values={"name": "updated", "age": 2}
        ) == 1
        single = await repo.where(User.username == "m-single").first()
        assert single is not None
        assert (single.name, single.age) == ("updated", 2)

        assert await repo.update_many(
            User.active == True, values={"name": "active"}
        ) == 80
        assert await repo.count(User.name == "active") == 80


        # Single and bulk delete use the same count contract. User is a
        # soft-delete model, so the rows remain observable with_deleted().
        assert await repo.delete(User.username == "m-single") == 1
        assert await repo.where(User.username == "m-single").first() is None
        assert (
                    await repo.query(User.username == "m-single").with_deleted().count()
                    == 1
                )

        assert await repo.delete_many(User.name == "active") == 80
        assert await repo.count(User.name == "active") == 0
        assert (
                    await repo.query(User.name == "active").with_deleted().count() == 80
                )
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_include_relationship(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        from tests.db._conformance import Profile

        await repo.create(
            User(
                id="home",
                username="home",
                name="Home",
                age=30,
                profile=Profile(street="100 Main", city="Oslo"),
                posts=[_p("p1", "keep", "home"), _p("p2", "drop", "home")],
            )
        )
        loaded = (
            await repo.query(User.username == "home")
            .include(Include(User.posts), User.profile)
            .all()
        )
        assert len(loaded) == 1
        user = loaded[0]
        assert user.profile.city == "Oslo"
        assert sorted(p.title for p in user.posts) == ["drop", "keep"]

        loaded = await repo.query(User.username == "home").all()
        assert len(loaded) == 1
        user = loaded[0]
        assert user.profile.city == "Oslo"
        assert user.posts == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_include_filter_posts_returns_all_users(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("u1", "u1", age=1, posts=[_p("pp1", "keep", "u1")]),
                _u("u2", "u2", age=2, posts=[_p("pp2", "drop", "u2")]),
                _u("u3", "u3", age=3),
            ]
        )
        loaded = (
            await repo.query()
            .include(Include(User.posts, filter=Post.title == "keep"))
            .all()
        )

        assert len(loaded) == 3
        for row in loaded:
            assert all(p.title == "keep" for p in row.posts)
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Relationship query and loading conformance.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_relation_any_and_nested_logical_filters(kind):
    db = await database_for(kind, [User, Post])
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u("any-1", "any-1", age=10),
                _u("any-2", "any-2", age=20),
                _u("any-3", "any-3", age=30),
                *[
                    _u(
                        f"any-{i:03d}",
                        f"any-{i:03d}",
                        age=min(40 + i, 120),
                    )
                    for i in range(4, 101)
                ],
            ]
        )
        await db.repository(Post).create_many(
            [
                _p("any-p1", "keep", "any-1"),
                _p("any-p2", "drop", "any-2"),
            ]
        )

        matching = await repo.query(
            User.posts.any((Post.title == "keep") & (Post.id == "any-p1"))
        ).all()
        assert [user.id for user in matching] == ["any-1"]

        # RelationAny can participate in a normal logical expression without
        # requiring callers to explicitly include the related collection.
        matching = await repo.query(
            User.posts.any(Post.title == "keep") | (User.age == 30)
        ).order_by(User.id.asc()).all()
        assert [user.id for user in matching] == ["any-1", "any-3"]
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_and_filtered_includes(kind):
    db = await database_for(kind, [NestedCompany, NestedEmployee, NestedDepartment])
    try:
        company_repo = db.repository(NestedCompany)
        employee_repo = db.repository(NestedEmployee)
        department_repo = db.repository(NestedDepartment)

        await department_repo.create_many(
            [
                NestedDepartment(id="rel-d1", name="engineering"),
                NestedDepartment(id="rel-d2", name="support"),
            ]
        )
        await company_repo.create(NestedCompany(id="rel-c1", name="Renus"))
        await employee_repo.create_many(
            [
                NestedEmployee(
                    id="rel-e1",
                    name="Ada",
                    company_id="rel-c1",
                    department_id="rel-d1",
                ),
                NestedEmployee(
                    id="rel-e2",
                    name="Grace",
                    company_id="rel-c1",
                    department_id="rel-d2",
                ),
                *[
                    NestedEmployee(
                        id=f"rel-e{i:03d}",
                        name=f"Employee-{i:03d}",
                        company_id="rel-c1",
                        department_id=f"rel-d{i}",
                    )
                    for i in range(3, 101)
                ],
            ]
        )

        nested = Include(
            NestedCompany.employees,
            nested=(Include(NestedEmployee.department),),
        )
        loaded = await company_repo.query().include(nested).first()
        assert loaded is not None
        assert len(loaded.employees) == 100
        assert [
            (employee.name, employee.department.name)
            for employee in loaded.employees[:2]
        ] == [("Ada", "engineering"), ("Grace", "support")]

        filtered = Include(
            NestedCompany.employees,
            filter=NestedEmployee.name == "Ada",
            nested=(Include(NestedEmployee.department),),
        )
        loaded = await company_repo.query().include(filtered).first()
        assert loaded is not None
        assert [(employee.name, employee.department.name) for employee in loaded.employees] == [
            ("Ada", "engineering")
        ]
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_joined_and_lazy_loading_strategies(kind):
    db = await database_for(kind, [JoinedParent, LazyParent, StrategyChild])
    try:
        joined_repo = db.repository(JoinedParent)
        lazy_repo = db.repository(LazyParent)
        child_repo = db.repository(StrategyChild)

        await joined_repo.create(JoinedParent(id="joined-1", name="joined"))
        await lazy_repo.create(LazyParent(id="lazy-1", name="lazy"))
        await child_repo.create_many(
            [
                StrategyChild(
                    id="strategy-j1",
                    joined_parent_id="joined-1",
                    label="joined-child",
                ),
                StrategyChild(
                    id="strategy-s1",
                    lazy_parent_id="lazy-1",
                    label="lazy-child",
                ),
                *[
                    StrategyChild(
                        id=f"strategy-{i:03d}",
                        joined_parent_id="joined-1" if i < 51 else "",
                        lazy_parent_id="lazy-1" if i >= 51 else "",
                        label=f"child-{i:03d}",
                    )
                    for i in range(2, 100)
                ],
            ]
        )

        # JOINED relationships are loaded by an ordinary query.
        joined = await joined_repo.query().first()
        assert joined is not None
        assert len(joined.children) == 50
        assert joined.children[0].label == "joined-child"

        # lazy relationships require an explicit include and are loaded in
        # the same result shape when requested.
        lazy = await lazy_repo.query().first()
        assert lazy is not None
        assert lazy.children == []
        lazy = await lazy_repo.query().include(LazyParent.children).first()
        assert lazy is not None
        assert len(lazy.children) == 50
        assert lazy.children[0].label == "lazy-child"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_duplicate_link_reconciliation(kind):
    db = await database_for(kind, [Employee, Role])
    try:
        employee_repo = db.repository(Employee)
        role_repo = db.repository(Role)
        roles = [
            Role(id="dup-role", name="shared"),
            *[Role(id=f"dup-role-{i:03d}", name=f"role-{i:03d}") for i in range(1, 100)],
        ]
        await role_repo.create_many(roles)

        employee = Employee(
            id="dup-employee",
            name="duplicate-safe",
            roles=[
                Role(id="dup-role", name="shared"),
                Role(id="dup-role", name="shared"),
            ],
        )
        await employee_repo.create(employee)
        await employee_repo.create_many(
            [
                Employee(
                    id=f"dup-employee-{i:03d}",
                    name=f"employee-{i:03d}",
                    roles=[Role(id=f"dup-role-{i:03d}", name=f"role-{i:03d}")],
                )
                for i in range(1, 100)
            ]
        )
        assert await _row_counts(db, "employees", "roles", "employee_roles") == {
            "employees": 100,
            "roles": 100,
            "employee_roles": 100,
        }

        loaded = await employee_repo.query(Employee.id == "dup-employee").include(Employee.roles).first()
        assert loaded is not None
        assert [role.id for role in loaded.roles] == ["dup-role"]

        # Re-saving the same duplicate collection must reconcile to one link,
        # not accumulate duplicate junction rows.
        loaded.roles = [
            Role(id="dup-role", name="shared"),
            Role(id="dup-role", name="shared"),
        ]
        await employee_repo.save(loaded)
        assert await _row_counts(db, "employees", "roles", "employee_roles") == {
            "employees": 100,
            "roles": 100,
            "employee_roles": 100,
        }
        local_column, _ = _junction_columns(
            Employee.metadata(),
            Employee.metadata().relationships["roles"],
            Role.metadata(),
        )
        duplicate_links = await db.adapter("primary").execute_query(
            QueryAST(
                source=_row_count_model("employee_roles"),
                filters=(
                    Path(_row_count_model("employee_roles"), (local_column,))
                    == "dup-employee",
                ),
            )
        )
        assert len(duplicate_links) == 1
        loaded_again = await employee_repo.query(Employee.id == "dup-employee").include(Employee.roles).first()
        assert loaded_again is not None
        assert [role.id for role in loaded_again.roles] == ["dup-role"]
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Nested model field validation and relationship behavior.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_model_list_field_is_validated_before_save(kind):
    db = await database_for(kind, [UnannotatedEmbeddedOwner])
    try:
        repo = db.repository(UnannotatedEmbeddedOwner)

        with pytest.raises(ValidationError) as exc_info:
            await repo.create(
                UnannotatedEmbeddedOwner(
                    id="unannotated-invalid",
                    data=[{"id": "1", "name": "invalid"}],
                )
            )
        assert exc_info.value.errors == {
            "data": [["type_error", ["int", "str"]]],
        }
        assert await repo.count() == 0

        created = await repo.create(
            UnannotatedEmbeddedOwner(
                id="unannotated-valid",
                data=[{"id": 1, "name": "valid"}],
            )
        )
        assert isinstance(created.data[0], UnannotatedEmbeddedChild)
        assert created.data[0].id == 1

        loaded = await repo.query().first()
        assert loaded is not None
        assert isinstance(loaded.data[0], UnannotatedEmbeddedChild)
        assert loaded.data[0].name == "valid"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_relationship_validation(kind):
    """Validate nested payloads for every relationship kind on every adapter."""
    db = await database_for(
        kind,
        [Item, Citizen, Passport, User, Post, Employee, Dept, Role],
    )
    try:
        cases = (
            (
                Item,
                "address",
                Profile,
                {
                    "id": "nv-embedded",
                    "name": "widget",
                    "address": {"street": "one", "city": "two"},
                },
                {
                    "id": "nv-embedded",
                    "name": "widget",
                    "address": {"street": "one", "city": 2},
                },
                "address.city",
            ),
            (
                Item,
                "tags",
                Tag,
                {
                    "id": "nv-embedded-many",
                    "name": "kit",
                    "tags": [{"name": "blue"}],
                },
                {
                    "id": "nv-embedded-many",
                    "name": "kit",
                    "tags": [{"name": 2}],
                },
                "tags[0].name",
            ),
            (
                Citizen,
                "passport",
                Passport,
                {
                    "id": "nv-one-to-one",
                    "name": "Ada",
                    "passport": {"id": "nv-passport", "number": "P-1"},
                },
                {
                    "id": "nv-one-to-one",
                    "name": "Ada",
                    "passport": {"id": "nv-passport", "number": 1},
                },
                "passport.number",
            ),
            (
                User,
                "posts",
                Post,
                {
                    "id": "nv-one-to-many",
                    "username": "ada",
                    "posts": [{"id": "nv-post", "title": "Hello"}],
                },
                {
                    "id": "nv-one-to-many",
                    "username": "ada",
                    "posts": [{"id": "nv-post", "title": 1}],
                },
                "posts[0].title",
            ),
            (
                Employee,
                "dept",
                Dept,
                {
                    "id": "nv-many-to-one",
                    "name": "Ada",
                    "dept_id": "nv-dept",
                    "dept": {"id": "nv-dept", "name": "engineering"},
                },
                {
                    "id": "nv-many-to-one",
                    "name": "Ada",
                    "dept_id": "nv-dept",
                    "dept": {"id": "nv-dept", "name": 1},
                },
                "dept.name",
            ),
            (
                Employee,
                "dept",
                Dept,
                {
                    "id": "nv-many-to-one",
                    "name": "Ada",
                    "dept_id": "nv-dept",
                    "dept": {"id": "nv-dept", "name": "engineering"},
                },
                {
                    "id": "nv-many-to-one",
                    "name": "Ada",
                    "dept_id": 123,
                    "dept": {"id": "nv-dept", "name": "ok"},
                },
                "dept_id",
            ),
            (
                Employee,
                "roles",
                Role,
                {
                    "id": "nv-many-to-many",
                    "name": "Ada",
                    "roles": [{"id": "nv-role", "name": "admin"}],
                },
                {
                    "id": "nv-many-to-many",
                    "name": "Ada",
                    "roles": [{"id": "nv-role", "name": 1}],
                },
                "roles[0].name",
            ),
        )

        for owner, relationship, target, valid, invalid, error_path in cases:
            validated = owner(valid)
            value = getattr(validated, relationship)
            if isinstance(value, list):
                assert value and isinstance(value[0], target)
            else:
                assert isinstance(value, target)

            with pytest.raises(ValidationError) as exc_info:
                owner(invalid)
            error_field = error_path.split(".", 1)[0].split("[", 1)[0]
            assert any(
                isinstance(error, (list, tuple)) and error[0] == "type_error"
                for error in exc_info.value.errors[error_field]
            )
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_relationship_target_projections(kind):
    """Project scalar fields from every supported relationship target type."""
    db = await database_for(
        kind,
        [User, Post, Citizen, Passport, Dept, Employee, Role],
    )
    try:
        user_repo = db.repository(User)
        post_repo = db.repository(Post)
        citizen_repo = db.repository(Citizen)
        passport_repo = db.repository(Passport)
        dept_repo = db.repository(Dept)
        employee_repo = db.repository(Employee)
        role_repo = db.repository(Role)

        # OneToMany: 100 posts reference 100 users; project the child endpoint.
        await user_repo.create_many(
            [_u(f"rp-u{i:03d}", f"rp-u{i:03d}", age=i) for i in range(100)]
        )
        await post_repo.create_many(
            [_p(f"rp-p{i:03d}", f"post-{i:03d}", f"rp-u{i:03d}") for i in range(100)]
        )
        post_projection = await (
            post_repo.query()
            .select(Post.user_id, Post.title)
            .order_by(Post.title.asc())
            .all()
        )
        assert len(post_projection) == 100
        assert post_projection[0] == {"user_id": "rp-u000", "title": "post-000"}
        loaded_user = await (
            user_repo.query(User.id == "rp-u000").include(User.posts).first()
        )
        assert loaded_user is not None
        assert [post.title for post in loaded_user.posts] == ["post-000"]

        # OneToOne: 100 passports reference 100 citizens; project the target.
        await citizen_repo.create_many(
            [Citizen(id=f"rp-c{i:03d}", name=f"citizen-{i:03d}") for i in range(100)]
        )
        await passport_repo.create_many(
            [
                Passport(
                    id=f"rp-pass{i:03d}",
                    citizen_id=f"rp-c{i:03d}",
                    number=f"passport-{i:03d}",
                )
                for i in range(100)
            ]
        )
        passport_projection = await (
            passport_repo.query()
            .select(Passport.citizen_id, Passport.number)
            .order_by(Passport.number.asc())
            .all()
        )
        assert len(passport_projection) == 100
        assert passport_projection[0] == {
            "citizen_id": "rp-c000",
            "number": "passport-000",
        }
        loaded_citizen = await (
            citizen_repo.query(Citizen.id == "rp-c000")
            .include(Citizen.passport)
            .first()
        )
        assert loaded_citizen is not None
        assert loaded_citizen.passport.number == "passport-000"

        # ManyToOne: 100 employees point to 100 departments; project the holder.
        await dept_repo.create_many(
            [Dept(id=f"rp-d{i:03d}", name=f"dept-{i:03d}") for i in range(100)]
        )
        await employee_repo.create_many(
            [
                Employee(
                    id=f"rp-e{i:03d}",
                    name=f"employee-{i:03d}",
                    dept_id=f"rp-d{i:03d}",
                )
                for i in range(100)
            ]
        )
        employee_projection = await (
            employee_repo.query()
            .select(Employee.dept_id, Employee.name)
            .order_by(Employee.name.asc())
            .all()
        )
        assert len(employee_projection) == 100
        assert employee_projection[0] == {
            "dept_id": "rp-d000",
            "name": "employee-000",
        }
        loaded_employee = await (
            employee_repo.query(Employee.id == "rp-e000")
            .include(Employee.dept)
            .first()
        )
        assert loaded_employee is not None
        assert loaded_employee.dept.name == "dept-000"

        # ManyToMany: 100 employees each link to one role; project the target
        # endpoint and verify the link is still populated through include().
        roles = [Role(id=f"rp-r{i:03d}", name=f"role-{i:03d}") for i in range(100)]
        await role_repo.create_many(roles)
        await employee_repo.create_many(
            [
                Employee(
                    id=f"rp-m{i:03d}",
                    name=f"member-{i:03d}",
                    roles=[roles[i]],
                )
                for i in range(100)
            ]
        )
        role_projection = await (
            role_repo.query()
            .select(Role.id, Role.name)
            .order_by(Role.name.asc())
            .all()
        )
        assert len(role_projection) == 100
        assert role_projection[0] == {"id": "rp-r000", "name": "role-000"}
        loaded_member = await (
            employee_repo.query(Employee.id == "rp-m000")
            .include(Employee.roles)
            .first()
        )
        assert loaded_member is not None
        assert [role.name for role in loaded_member.roles] == ["role-000"]
    finally:
        await cleanup(db)



def _deep_embedded_value(prefix: str = "") -> DeepEmbedded1:
    """Build all seven embedded levels, applying ``prefix`` to every name."""
    value: Any = DeepEmbedded7(
        name=f"{prefix}deep-embedded-7",
        value=f"{prefix}embedded-7",
    )
    for level, model in zip(
        range(6, 1, -1),
        (
            DeepEmbedded6,
            DeepEmbedded5,
            DeepEmbedded4,
            DeepEmbedded3,
            DeepEmbedded2,
        ),
    ):
        value = model(name=f"{prefix}deep-embedded-{level}", child=value)
    return DeepEmbedded1(name=f"{prefix}deep-embedded-1", child=value)


def _deep_many_value(prefix: str = "") -> list[DeepMany1]:
    """Build all seven embedded-many levels, applying ``prefix`` to every name."""
    value: Any = DeepMany7(name=f"{prefix}deep-many-7")
    for level, model in zip(
        range(6, 1, -1),
        (DeepMany6, DeepMany5, DeepMany4, DeepMany3, DeepMany2),
    ):
        value = model(name=f"{prefix}deep-many-{level}", children=[value])
    return [DeepMany1(name=f"{prefix}deep-many-1", children=[value])]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_seven_level_nested_model_fields_roundtrip(kind):
    db = await database_for(kind, [DeepRoot])
    try:
        root_repo = db.repository(DeepRoot)
        roots = [
            DeepRoot(
                id="deep-1",
                name="deep-root-1",
                embedded=_deep_embedded_value("root1-"),
                many=_deep_many_value("root1-"),
            ),
            DeepRoot(
                id="deep-2",
                name="deep-root-2",
                embedded=_deep_embedded_value("root2-"),
                many=_deep_many_value("root2-"),
            ),
            DeepRoot(
                id="deep-3",
                name="deep-root-3",
                embedded=_deep_embedded_value("root3-"),
                many=_deep_many_value("root3-"),
            ),
        ]
        await root_repo.create_many(roots)

        assert await _row_counts(db, "deeproots") == {"deeproots": 3}
        loaded = await root_repo.where(DeepRoot.id == "deep-2").first()
        assert loaded is not None
        current = loaded.embedded
        for _ in range(6):
            assert current is not None
            current = current.child
        assert current is not None
        assert current.value == "root2-embedded-7"
        assert loaded.many[0].children[0].children[0].name == "root2-deep-many-3"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_model_list_field(kind):
    db = await database_for(kind, [Item])
    try:
        repo = db.repository(Item)
        tables = ["items"]

        await repo.create_many(
            [Item(id="m1", name="kit", tags=[Tag(name="a"), Tag(name="b")])]
        )
        before = await _row_counts(db, *tables)
        assert before == {"items": 1}, before

        loaded = (await repo.query().all())[0]
        assert sorted(t.name for t in loaded.tags) == ["a", "b"]

        assert [row.id for row in await repo.query(Item.tags.name == "a").all()] == ["m1"]
        assert [row.id for row in await repo.query(Item.tags.name.in_("b")).all()] == ["m1"]

        await repo.delete_many()
        after = await _row_counts(db, *tables)
        assert after == {t: 0 for t in tables}, after
        assert await repo.count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_one_to_one_relationship(kind):
    db = await database_for(kind, [Citizen, Passport])
    try:
        repo = db.repository(Citizen)
        await repo.create(
            Citizen(id="c1", name="alice", passport=Passport(id="p1", number="X123"))
        )
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }

        loaded = (await repo.query().include(Citizen.passport).all())[0]
        assert loaded.passport.number == "X123"

        # Deleting the citizen cascades the related passport row too.
        await repo.delete(loaded)
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 0,
            "passports": 0,
        }
        assert await db.repository(Passport).query().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_one_to_many_relationship(kind):
    db = await database_for(kind, [User, Post])
    try:
        repo = db.repository(User)
        await repo.create(
            _u("r1", "owner", age=1, posts=[_p("rp1", "x", "r1"), _p("rp2", "y", "r1")])
        )
        assert await _row_counts(db, "users", "posts") == {"users": 1, "posts": 2}

        loaded = (await repo.query().include(User.posts).all())[0]
        assert sorted(p.title for p in loaded.posts) == ["x", "y"]

        # ``User`` is soft-delete: the child posts are hard-cascaded away, while
        # the parent row is retained (marked deleted) rather than dropped. Both
        # effects happen across every adapter.
        await repo.delete(loaded)
        assert await _row_counts(db, "users", "posts") == {"users": 1, "posts": 0}
        assert await repo.count() == 0  # active view hides the soft-deleted row
        assert await db.repository(Post).query().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_one_relationship(kind):
    db = await database_for(kind, [Employee, Dept])
    try:
        emp_repo = db.repository(Employee)
        dept_repo = db.repository(Dept)
        await dept_repo.create(Dept(id="d1", name="eng"))
        await emp_repo.create(Employee(id="e1", name="bob", dept_id="d1"))
        assert await _row_counts(db, "employees", "depts") == {
            "employees": 1,
            "depts": 1,
        }

        loaded = (await emp_repo.query().include(Employee.dept).all())[0]
        assert loaded.dept.name == "eng"
    finally:
        await cleanup(db)


def _deep_relation_value(family_name: str):
    family = DEEP_RELATION_FAMILIES[family_name]
    relation_name = {
        "one_to_one": "child",
        "one_to_many": "children",
        "many_to_one": "parent",
        "many_to_many": "children",
    }[family_name]
    current: Any = family[-1](id=f"{family_name}-7")
    for model in reversed(family[:-1]):
        current = model(id=f"{family_name}-{len(family) - len(model.__name__)}", **{relation_name: [current] if relation_name in ("children",) else current})
    return current


def _deep_relation_include(family_name: str):
    family = DEEP_RELATION_FAMILIES[family_name]
    relation_name = {
        "one_to_one": "child",
        "one_to_many": "children",
        "many_to_one": "parent",
        "many_to_many": "children",
    }[family_name]
    nested = None
    for owner in reversed(family[:-1]):
        path = getattr(owner, relation_name)
        nested = Include(path) if nested is None else Include(path, nested=(nested,))
    return nested


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize("family_name", sorted(DEEP_RELATION_FAMILIES))
async def test_seven_level_relations_and_nested_queries(kind, family_name):
    family = DEEP_RELATION_FAMILIES[family_name]
    db = await database_for(kind, list(family))
    try:
        root_cls = family[0]
        root = _deep_relation_value(family_name)
        await db.repository(root_cls).create(root)

        tables = [model.metadata().table for model in family]
        if family_name == "many_to_many":
            tables.extend(
                rel.through
                for model in family[:-1]
                for rel in model.metadata().relationships.values()
                if rel.through
            )
        counts = await _row_counts(db, *tables)
        assert counts == {table: 1 for table in tables}

        include = _deep_relation_include(family_name)
        relation_name = {
            "one_to_one": "child",
            "one_to_many": "children",
            "many_to_one": "parent",
            "many_to_many": "children",
        }[family_name]
        relation_path = getattr(root_cls, relation_name)
        relation_meta = root_cls.metadata().relationships[relation_name]
        target_cls = relation_meta.target
        related = getattr(root, relation_name)
        related = related[0] if isinstance(related, list) else related
        relation_match = relation_path.any(
            Path(target_cls, (target_cls.metadata().primary_key_field,))
            == getattr(related, target_cls.metadata().primary_key_field)
        )
        relation_matches = await db.repository(root_cls).query(relation_match).all()
        assert [row.id for row in relation_matches] == [root.id]


        loaded = (await db.repository(root_cls).query().include(include).all())[0]
        current = loaded
        relation_name = {
            "one_to_one": "child",
            "one_to_many": "children",
            "many_to_one": "parent",
            "many_to_many": "children",
        }[family_name]
        for _ in range(6):
            current = getattr(current, relation_name)
            if relation_name in ("children",):
                assert len(current) == 1
                current = current[0]
        assert current.value == f"{family_name.replace('_', '-')}-7"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_relationship(kind):
    db = await database_for(kind, [Employee, Role])
    try:
        emp_repo = db.repository(Employee)
        role_repo = db.repository(Role)

        rel = Employee.metadata().relationships["roles"]
        assert rel.kind == RelationshipKind.MANY_TO_MANY
        assert rel.through == "employee_roles"
        assert Role.metadata().table == "roles"

        await role_repo.create_many(
            [
                Role(id="r1", name="admin"),
                Role(id="r2", name="editor"),
                Role(id="r3", name="viewer"),
                Role(id="r4", name="owner"),
                Role(id="r5", name="guest"),
            ]
        )

        await emp_repo.create(
            Employee(
                id="e1",
                name="bob",
                roles=[Role(id="r1", name="admin"), Role(id="r2", name="editor")],
            )
        )

        # The junction table ``employee_roles`` captures the two links.
        assert await _row_counts(db, "employees", "roles", "employee_roles") == {
            "employees": 1,
            "roles": 5,
            "employee_roles": 2,
        }

        loaded = (await emp_repo.query().include(Employee.roles).all())[0]
        assert sorted(r.name for r in loaded.roles) == ["admin", "editor"]

        stored = await role_repo.query().all()
        assert {r.id for r in stored} == {"r1", "r2", "r3", "r4", "r5"}

        # Many-to-many is restrict: deleting an employee removes the junction
        # links and the employee row, but leaves the related roles intact.
        await emp_repo.delete(loaded)
        assert await _row_counts(db, "employees", "roles", "employee_roles") == {
            "employees": 0,
            "roles": 5,
            "employee_roles": 0,
        }
        assert {r.id for r in await role_repo.query().all()} == {
            "r1",
            "r2",
            "r3",
            "r4",
            "r5",
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_filter_sort_limit_skip(kind):
    db = await database_for(kind, [Employee, Role])
    try:
        emp_repo = db.repository(Employee)
        role_repo = db.repository(Role)

        await role_repo.create_many(
            [
                Role(id="r1", name="admin"),
                Role(id="r2", name="editor"),
                Role(id="r3", name="viewer"),
                Role(id="r4", name="owner"),
                Role(id="r5", name="guest"),
            ]
        )
        await emp_repo.create_many(
            [
                Employee(
                    id="e1",
                    name="alice",
                    roles=[Role(id="r1", name="admin"), Role(id="r2", name="editor")],
                ),
                Employee(
                    id="e2",
                    name="bob",
                    roles=[Role(id="r1", name="admin"), Role(id="r3", name="viewer")],
                ),
                Employee(
                    id="e3",
                    name="carol",
                    roles=[Role(id="r5", name="guest")],
                ),
            ]
        )

        # Sort the parent query, skip one, limit to two; roles stay attached.
        rows = await (
            emp_repo.query()
            .order_by(Employee.name)
            .offset(1)
            .limit(2)
            .include(Employee.roles)
            .all()
        )
        assert [r.name for r in rows] == ["bob", "carol"]
        assert sorted(r.name for r in rows[0].roles) == ["admin", "viewer"]
        assert [r.name for r in rows[1].roles] == ["guest"]

        # Filter the parent query; each returned employee keeps its roles.
        rows = await (
            emp_repo.query(Employee.name == "alice").include(Employee.roles).all()
        )
        assert len(rows) == 1
        assert rows[0].id == "e1"
        assert sorted(r.name for r in rows[0].roles) == ["admin", "editor"]

        # The include filter narrows the loaded roles per employee.
        rows = (
            await emp_repo.query(Employee.name == "alice")
            .include(Include(Employee.roles, filter=Role.name == "editor"))
            .all()
        )
        assert len(rows) == 1
        assert [r.name for r in rows[0].roles] == ["editor"]

        # Combine a parent filter with an include filter across employees.
        rows = (
            await emp_repo.query(Employee.name.in_(["alice", "bob"]))
            .order_by(Employee.name)
            .include(Include(Employee.roles, filter=Role.name == "admin"))
            .all()
        )
        assert [r.name for r in rows] == ["alice", "bob"]
        assert all([r.name for r in row.roles] == ["admin"] for row in rows)
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Cascades: on update & on delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_update_one_to_many(kind):
    db = await database_for(kind, [User, Post])
    try:
        await db.repository(User).create(
            _u("u1", "owner", age=1, posts=[_p("p1", "x", "u1"), _p("p2", "y", "u1")])
        )

        owner = (await db.repository(User).query().include(User.posts).all())[0]
        owner.id = "u2"
        await db.repository(User).save(owner)

        posts = await db.repository(Post).query().order_by(Post.title).all()
        assert {p.id for p in posts} == {"p1", "p2"}
        assert all(p.user_id == "u2" for p in posts)
        assert await db.repository(Post).query().count() == 2
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_update_one_to_one(kind):
    db = await database_for(kind, [Citizen, Passport])
    try:
        await db.repository(Citizen).create(
            Citizen(id="c1", name="alice", passport=Passport(id="p1", number="X123"))
        )

        # Changing the parent id cascades to the one-to-one child foreign key.
        citizen = (
            await db.repository(Citizen).query().include(Citizen.passport).all()
        )[0]
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }

        citizen.id = "c2"
        await db.repository(Citizen).save(citizen)

        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }
        passports = await db.repository(Passport).query().all()
        assert len(passports) == 1
        assert passports[0].citizen_id == "c2"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_delete_one_to_one(kind):
    db = await database_for(kind, [Citizen, Passport])
    try:
        repo = db.repository(Citizen)
        await repo.create_many(
            [
                Citizen(
                    id="c1",
                    name="alice",
                    passport=Passport(id="p1", number="X123"),
                ),
                Citizen(
                    id="c2",
                    name="bob",
                    passport=Passport(id="p2", number="Y456"),
                ),
            ]
        )

        loaded = (await repo.query().include(Citizen.passport).all())[0]
        await repo.delete(loaded)

        # Deleting one citizen cascades only that citizen's passport.
        assert await _row_counts(db, "citizens", "passports") == {
            "citizens": 1,
            "passports": 1,
        }
        remaining = await db.repository(Passport).query().all()
        assert {p.id for p in remaining} in ({"p1"}, {"p2"})
        assert await db.repository(Citizen).query().count() == 1
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_cascade_on_delete_one_to_many_isolates_siblings(kind):
    db = await database_for(kind, [User, Post])
    try:
        repo = db.repository(User)
        await repo.create_many(
            [
                _u(
                    "r1",
                    "owner1",
                    age=1,
                    posts=[_p("p1", "x", "r1"), _p("p2", "y", "r1")],
                ),
                _u("r2", "owner2", age=2, posts=[_p("p3", "z", "r2")]),
            ]
        )

        loaded = (await repo.query(User.id == "r1").include(User.posts).all())[0]
        await repo.delete(loaded)

        assert (await db.repository(Post).query().all())[0].user_id == "r2"
        assert await db.repository(Post).query().count() == 1
        assert await db.repository(Post).exists(Post.id == "p3") is True
        assert await db.repository(Post).exists(Post.id == "p1") is False
        assert await repo.query(User.id == "r2").count() == 1
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_one_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    owner, child, _fk = _o2o_pair(
        name,
        on_save=action.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=ReferentialAction.CASCADE.value,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(owner(id="p1", name="p", detail=child(id="d1", label="x")))
        child_count = await db.repository(child).query().count()
        if action is SaveAction.CASCADE:
            assert child_count == 1
        else:
            assert child_count == 0
        assert await _row_counts(db, owner_table, child_table) == {
            owner_table: 1,
            child_table: child_count,
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_one_on_delete(kind, action):
    name = "OnDelete" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2o_pair(
        name,
        on_save=SaveAction.CASCADE.value,
        on_delete=action.value,
        on_update=ReferentialAction.CASCADE.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(owner(id="p1", name="p", detail=child(id="d1", label="x")))
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await repo.query().include(owner.detail).all())[0]
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await repo.delete(loaded)
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await repo.delete(loaded)
            children = await db.repository(child).query().all()
            after = {
                owner_table: await repo.query().count(),
                child_table: len(children),
            }
            if action is ReferentialAction.CASCADE:
                assert after == {owner_table: 0, child_table: 0}
            else:
                assert after == {owner_table: 0, child_table: 1}
                if action is ReferentialAction.SET_NULL:
                    assert getattr(children[0], fk) is None
                elif action is ReferentialAction.SET_DEFAULT:
                    assert getattr(children[0], fk) == "unknown"
                else:
                    assert getattr(children[0], fk) == "p1"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_one_on_update(kind, action):
    name = "OnUpdate" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2o_pair(
        name,
        on_save=SaveAction.NO_ACTION.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=action.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        await db.repository(child).create(child(id="d1", label="x", **{fk: "p1"}))
        await db.repository(owner).create(owner(id="p1", name="p"))
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await db.repository(owner).query().include(owner.detail).all())[0]
        loaded.id = "p2"
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await db.repository(owner).save(loaded)
            stored = (await db.repository(owner).query().all())[0]
            assert stored.id == "p1"
            children = await db.repository(child).query().all()
            assert len(children) == 1
            assert getattr(children[0], fk) == "p1"
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await db.repository(owner).save(loaded)
            children = await db.repository(child).query().all()
            assert len(children) == 1
            if action is ReferentialAction.CASCADE:
                assert getattr(children[0], fk) == "p2"
            elif action is ReferentialAction.SET_NULL:
                assert getattr(children[0], fk) is None
            elif action is ReferentialAction.SET_DEFAULT:
                assert getattr(children[0], fk) == "unknown"
            else:
                assert getattr(children[0], fk) == "p1"
            assert await _row_counts(db, owner_table, child_table) == before
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_many_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    owner, child, _fk = _o2m_pair(
        name,
        on_save=action.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=ReferentialAction.CASCADE.value,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                children=[
                    child(id="d1", label="x"),
                    child(id="d2", label="y"),
                    child(id="d3", label="z"),
                ],
            )
        )
        child_count = await db.repository(child).query().count()
        if action is SaveAction.CASCADE:
            assert child_count == 3
        else:
            assert child_count == 0
        assert await _row_counts(db, owner_table, child_table) == {
            owner_table: 1,
            child_table: child_count,
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_many_on_delete(kind, action):
    name = "OnDelete" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2m_pair(
        name,
        on_save=SaveAction.CASCADE.value,
        on_delete=action.value,
        on_update=ReferentialAction.CASCADE.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                children=[
                    child(id="d1", label="x"),
                    child(id="d2", label="y"),
                    child(id="d3", label="z"),
                ],
            )
        )
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await repo.query().include(owner.children).all())[0]
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await repo.delete(loaded)
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await repo.delete(loaded)
            children = await db.repository(child).query().all()
            after = {
                owner_table: await repo.query().count(),
                child_table: len(children),
            }
            if action is ReferentialAction.CASCADE:
                assert after == {owner_table: 0, child_table: 0}
            else:
                assert after == {owner_table: 0, child_table: 3}
                if action is ReferentialAction.SET_NULL:
                    assert all(getattr(c, fk) is None for c in children)
                elif action is ReferentialAction.SET_DEFAULT:
                    assert all(getattr(c, fk) == "unknown" for c in children)
                else:
                    assert all(getattr(c, fk) == "p1" for c in children)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(ReferentialAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_one_to_many_on_update(kind, action):
    name = "OnUpdate" + "".join(w.capitalize() for w in action.value.split())
    fk_default = "unknown" if action is ReferentialAction.SET_DEFAULT else None
    owner, child, fk = _o2m_pair(
        name,
        on_save=SaveAction.NO_ACTION.value,
        on_delete=ReferentialAction.CASCADE.value,
        on_update=action.value,
        fk_default=fk_default,
    )
    owner_table = owner.metadata().table
    child_table = child.metadata().table
    db = await database_for(kind, [owner, child])
    try:
        await db.repository(child).create_many(
            [
                child(id="d1", label="x", **{fk: "p1"}),
                child(id="d2", label="y", **{fk: "p1"}),
                child(id="d3", label="z", **{fk: "p1"}),
            ]
        )
        await db.repository(owner).create(owner(id="p1", name="p"))
        before = await _row_counts(db, owner_table, child_table)
        loaded = (await db.repository(owner).query().include(owner.children).all())[0]
        loaded.id = "p2"
        if action is ReferentialAction.RESTRICT:
            with pytest.raises(IntegrityError):
                await db.repository(owner).save(loaded)
            stored = (await db.repository(owner).query().all())[0]
            assert stored.id == "p1"
            children = await db.repository(child).query().all()
            assert len(children) == 3
            assert all(getattr(c, fk) == "p1" for c in children)
            assert await _row_counts(db, owner_table, child_table) == before
        else:
            await db.repository(owner).save(loaded)
            children = await db.repository(child).query().all()
            assert len(children) == 3
            if action is ReferentialAction.CASCADE:
                assert all(getattr(c, fk) == "p2" for c in children)
            elif action is ReferentialAction.SET_NULL:
                assert all(getattr(c, fk) is None for c in children)
            elif action is ReferentialAction.SET_DEFAULT:
                assert all(getattr(c, fk) == "unknown" for c in children)
            else:
                assert all(getattr(c, fk) == "p1" for c in children)
            assert await _row_counts(db, owner_table, child_table) == before
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_many_to_one_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    holder, parent, fk = _m2o_pair(name, on_save=action.value)
    holder_table = holder.metadata().table
    parent_table = parent.metadata().table
    db = await database_for(kind, [holder, parent])
    try:
        repo = db.repository(holder)
        await repo.create_many(
            [
                holder(id="c1", label="x", parent=parent(id="p1", name="p")),
                holder(id="c2", label="y", parent=parent(id="p1", name="p")),
                holder(id="c3", label="z", parent=parent(id="p1", name="p")),
            ]
        )
        parent_count = await db.repository(parent).query().count()
        if action is SaveAction.CASCADE:
            assert parent_count == 1
        else:
            assert parent_count == 0
        assert await _row_counts(db, holder_table, parent_table) == {
            holder_table: 3,
            parent_table: parent_count,
        }
        stored = await repo.query().all()
        if action is SaveAction.CASCADE:
            assert all(getattr(o, fk) == "p1" for o in stored)
        else:
            assert all(getattr(o, fk) is None for o in stored)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_one_on_delete(kind):
    name = "OnDelete"
    holder, parent, fk = _m2o_pair(name, on_save=SaveAction.NO_ACTION.value)
    holder_table = holder.metadata().table
    parent_table = parent.metadata().table
    db = await database_for(kind, [holder, parent])
    try:
        await db.repository(parent).create(parent(id="p1", name="p"))
        await db.repository(holder).create_many(
            [
                holder(id="c1", label="x", **{fk: "p1"}),
                holder(id="c2", label="y", **{fk: "p1"}),
                holder(id="c3", label="z", **{fk: "p1"}),
            ]
        )
        before = await _row_counts(db, holder_table, parent_table)
        loaded = (await db.repository(holder).query().all())[0]
        await db.repository(holder).delete(loaded)
        after = await _row_counts(db, holder_table, parent_table)
        assert after == {holder_table: 2, parent_table: 1}
        holders = await db.repository(holder).query().all()
        assert len(holders) == 2
        assert all(getattr(h, fk) == "p1" for h in holders)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_one_on_update(kind):
    name = "OnUpdate"
    holder, parent, fk = _m2o_pair(name, on_save=SaveAction.NO_ACTION.value)
    holder_table = holder.metadata().table
    parent_table = parent.metadata().table
    db = await database_for(kind, [holder, parent])
    try:
        await db.repository(parent).create(parent(id="p1", name="p"))
        await db.repository(holder).create_many(
            [
                holder(id="c1", label="x", **{fk: "p1"}),
                holder(id="c2", label="y", **{fk: "p1"}),
                holder(id="c3", label="z", **{fk: "p1"}),
            ]
        )
        before = await _row_counts(db, holder_table, parent_table)
        loaded = await db.repository(holder).query().first()
        await db.repository(holder).query(holder.id == "c1").update({"id": "cp"})
        loaded = await db.repository(holder).query(holder.id == "cp").first()
        assert loaded.id == "cp"
        assert loaded.label == "x"
        assert await _row_counts(db, holder_table, parent_table) == before
        holders = await db.repository(holder).query().all()
        assert len(holders) == 3
        assert all(getattr(h, fk) == "p1" for h in holders)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "action", list(SaveAction), ids=lambda a: a.value.replace(" ", "_")
)
async def test_many_to_many_on_save(kind, action):
    name = "OnSave" + "".join(w.capitalize() for w in action.value.split())
    owner, target, through = _mtm_pair(name, on_save=action.value)
    owner_table = owner.metadata().table
    target_table = target.metadata().table
    db = await database_for(kind, [owner, target])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                items=[target(id="r1", name="a"), target(id="r2", name="b")],
            )
        )
        target_count = await db.repository(target).query().count()
        if action is SaveAction.CASCADE:
            assert target_count == 2
        else:
            assert target_count == 0
        assert await _row_counts(db, owner_table, target_table, through) == {
            owner_table: 1,
            target_table: target_count,
            through: target_count,
        }
        loaded = (await repo.query().include(owner.items).all())[0]
        if action is SaveAction.CASCADE:
            assert sorted(i.name for i in loaded.items) == ["a", "b"]
        else:
            assert loaded.items == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_on_delete(kind):
    name = "OnDelete"
    owner, target, through = _mtm_pair(name, on_save=SaveAction.CASCADE.value)
    owner_table = owner.metadata().table
    target_table = target.metadata().table
    db = await database_for(kind, [owner, target])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                items=[target(id="r1", name="a"), target(id="r2", name="b")],
            )
        )
        before = await _row_counts(db, owner_table, target_table, through)
        assert before == {owner_table: 1, target_table: 2, through: 2}
        loaded = (await repo.query().all())[0]
        await repo.delete(loaded)
        assert await _row_counts(db, owner_table, target_table, through) == {
            owner_table: 0,
            target_table: 2,
            through: 0,
        }
        assert await repo.query().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_many_to_many_on_update(kind):
    name = "OnUpdate"
    owner, target, through = _mtm_pair(name, on_save=SaveAction.CASCADE.value)
    owner_table = owner.metadata().table
    target_table = target.metadata().table
    db = await database_for(kind, [owner, target])
    try:
        repo = db.repository(owner)
        await repo.create(
            owner(
                id="p1",
                name="p",
                items=[target(id="r1", name="a"), target(id="r2", name="b")],
            )
        )
        loaded = (await repo.query().include(owner.items).all())[0]
        loaded.items = [target(id="r1", name="a")]
        await repo.save(loaded)
        assert await _row_counts(db, owner_table, target_table, through) == {
            owner_table: 1,
            target_table: 2,
            through: 1,
        }
        reloaded = (await repo.query().include(owner.items).all())[0]
        assert sorted(i.name for i in reloaded.items) == ["a"]
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Cascades: on update & on delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_soft_delete_visibility(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(SoftUser)
        s1 = await repo.create(SoftUser(id="sd1", username="sd1"))
        await repo.create(SoftUser(id="sd2", username="sd2"))

        await repo.delete(s1)

        assert await repo.query().count() == 1
        assert await repo.query().with_deleted().count() == 2
        assert await repo.query().only_deleted().count() == 1
        only = await repo.query().only_deleted().first()
        assert only is not None
        assert only.username == "sd1"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_updates_refresh_updated_at(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        first = await repo.create(_u("timestamp-1", "timestamp-1", age=1))
        second = await repo.create(_u("timestamp-2", "timestamp-2", age=2))
        first_updated_at = first.updated_at
        second_updated_at = second.updated_at
        assert first_updated_at is not None
        assert second_updated_at is not None

        rows = await repo.update(
            User.username == "timestamp-1",
            values={"name": "changed"},
        )
        assert rows == 1
        updated = await repo.where(User.username == "timestamp-1").first()
        assert updated is not None
        assert updated.updated_at is not None
        assert _utc_timestamp(updated.updated_at) > _utc_timestamp(first_updated_at)


        rows_many = await repo.update_many(values={"name": "bulk"})
        assert rows_many == 2
        refreshed_first = await repo.where(User.username == "timestamp-1").first()
        refreshed_second = await repo.where(User.username == "timestamp-2").first()
        assert refreshed_first is not None
        assert refreshed_second is not None
        assert refreshed_first.updated_at is not None
        assert refreshed_second.updated_at is not None
        assert _utc_timestamp(refreshed_first.updated_at) > _utc_timestamp(updated.updated_at)
        assert _utc_timestamp(refreshed_second.updated_at) > _utc_timestamp(second_updated_at)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_repository_updates_validate_values_before_execution(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        account = await repo.create(_u("validation-1", "validation-1", age=10))

        with pytest.raises(ValidationError, match="'age' must be of type int"):
            await repo.where(User.username == "validation-1").update(
                {"age": "invalid"}
            )

        with pytest.raises(ValidationError, match="'age' must be less than or equal to 120"):
            await repo.where(User.username == "validation-1").update(
                {"age": 150}
            )

        with pytest.raises(ValidationError, match="Unknown field 'missing'"):
            await repo.update_many(User.active == True, values={"missing": 1})

        unchanged = await repo.where(User.username == "validation-1").first()
        assert unchanged is not None
        assert unchanged.age == account.age == 10
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_restore_soft_deleted_rows(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(SoftUser)
        deleted = await repo.create(SoftUser(id="restore-1", username="restore-1"))
        await repo.create(SoftUser(id="restore-2", username="restore-2"))
        await repo.delete(deleted)

        assert await repo.query().count() == 1
        assert await repo.query().only_deleted().count() == 1
        assert await repo.where(SoftUser.username == "restore-1").restore() == 1

        restored = await repo.where(SoftUser.username == "restore-1").first()
        assert restored is not None
        assert restored.is_deleted() is False
        assert await repo.query().count() == 2

        await repo.delete(restored)
        loaded_deleted = await repo.query().only_deleted().first()
        assert loaded_deleted is not None
        assert await repo.restore(loaded_deleted) == 1
        assert loaded_deleted.is_deleted() is False
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Hard delete (physical removal even for soft-delete models)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_hard_delete_many_ignores_soft_delete(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)  # soft_delete enabled
        await repo.create_many(
            [
                _u("hd1", "hd1", age=1),
                _u("hd2", "hd2", age=2),
            ]
        )

        # A normal delete soft-deletes: the row remains visible with_deleted.
        one = await repo.delete(User.username == "hd1")
        assert one == 1
        assert await repo.query().with_deleted().count() == 2

        # Hard delete physically removes it even though it is soft-deleted.
        removed = await repo.hard_delete_many(User.username == "hd1")
        assert removed == 1
        assert await repo.query().with_deleted().count() == 1
        assert await repo.query().only_deleted().count() == 0

        # Hard deletes a live row too.
        removed2 = await repo.hard_delete_many(User.username == "hd2")
        assert removed2 == 1
        assert await repo.query().with_deleted().count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_hard_delete_object_and_query(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        obj = await repo.create(
            _u("hd3", "hd3", age=3, posts=[_p("hp1", "post", "hd3")])
        )

        rows = await repo.hard_delete(obj)
        assert rows == 1
        assert await repo.query().with_deleted().count() == 0
        assert await db.repository(Post).query().count() == 0

        # Query.hard_delete() terminal method.
        await repo.create(_u("hd4", "hd4", age=4))
        qr = await repo.query(User.username == "hd4").hard_delete()
        assert qr == 1
        assert await repo.query().with_deleted().count() == 0
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Transactions & unit of work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_transaction_commit_and_rollback(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)

        async with db.transaction() as tx:
            await db.repository(User).create(_u("txc", "txc", age=1))

        assert await repo.exists(User.username == "txc") is True

        async with db.transaction() as tx:
            await db.repository(User).create(_u("txr", "txr", age=2))
            await tx.rollback()

        assert await repo.exists(User.username == "txr") is False

        with pytest.raises(RuntimeError, match="test"):
            async with db.transaction():
                await db.repository(User).create(_u("txr", "txr", age=2))
                raise RuntimeError("test")
        assert await repo.exists(User.username == "txr") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_commit_across_repositories(kind):
    db = await database_for(kind)
    adapter = db.adapter("primary")
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        repo = db.repository(User)
        async with db.unit_of_work() as uow:
            assert uow.is_active is True
            assert uow.is_committed is False

            u_users = uow.repository(User)
            u_posts = uow.repository(Post)
            await u_users.create(_u("uw1", "uw1", age=7))
            await u_posts.create(Post(id="up1", title="uow post", user_id="uw1"))
            await u_users.create(_u("uw2", "uw2", age=8))

            assert uow.users is u_users
            assert uow.posts is u_posts

            await uow.commit()
            assert uow.is_committed is True

        assert await repo.exists(User.username == "uw1") is True
        assert await repo.exists(User.username == "uw2") is True
        assert transaction_calls == [None]
        posts = await db.repository(Post).where(Post.user_id == "uw1").all()
        assert len(posts) == 1
        assert posts[0].title == "uow post"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_rollback_on_uncommitted_exit(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(_u("uwr1", "uwr1", age=1))
            await uow.repository(User).create(_u("uwr2", "uwr2", age=2))

        assert await repo.exists(User.username == "uwr1") is False
        assert await repo.exists(User.username == "uwr2") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_rollback_on_exception(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        with pytest.raises(RuntimeError):
            async with db.unit_of_work() as uow:
                await uow.repository(User).create(_u("uwx1", "uwx1", age=1))
                await uow.repository(User).create(_u("uwx2", "uwx2", age=2))
                raise RuntimeError("boom")

        assert await repo.exists(User.username == "uwx1") is False
        assert await repo.exists(User.username == "uwx2") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_unit_of_work_explicit_rollback(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(_u("uwz1", "uwz1", age=1))
            await uow.rollback()
            assert uow.is_committed is False
        assert await repo.exists(User.username == "uwz1") is False
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Transactions & unit of work
#
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_cross_repository_atomic_commit(kind):
    db = await database_for(kind)
    adapter = db.adapter("primary")
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        async with db.unit_of_work() as uow:
            users = uow.repository(User)
            posts = uow.repository(Post)
            await users.create(
                _u(
                    "a1",
                    "alice",
                    name="Alice",
                    age=30,
                    profile=Profile(city="Tehran", street="one"),
                )
            )
            await posts.create_many(
                [_p("ap1", "Alice first post", "a1"), _p("ap2", "Alice two post", "a1")]
            )
            await uow.commit()

        assert transaction_calls == [None]
        assert await db.repository(User).count() == 1
        assert await db.repository(Post).count() == 2
        assert await db.repository(User).exists(User.username == "alice") is True

        alice = (
            await db.repository(User)
            .query(User.username == "alice")
            .include(User.profile)
            .all()
        )[0]
        assert alice.profile.city == "Tehran"
        assert alice.profile.street == "one"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_cross_repository_rollback_on_error(kind):
    db = await database_for(kind)
    try:
        with pytest.raises(ValueError, match="Simulated transfer failure"):
            async with db.unit_of_work() as uow:
                await uow.repository(User).create(
                    _u(
                        "b1",
                        "bob",
                        name="Bob",
                        age=40,
                        profile=Profile(city="Shiraz", street="two"),
                    )
                )
                await uow.repository(Post).create(_p("bp1", "Bob post", "b1"))
                raise ValueError("Simulated transfer failure")

        assert await db.repository(User).count() == 0
        assert await db.repository(Post).count() == 0
        assert await _row_counts(db, "users", "posts") == {
            "users": 0,
            "posts": 0,
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_auto_rollback_on_uncommitted_exit(kind):
    db = await database_for(kind)
    try:
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(
                _u(
                    "c1",
                    "charlie",
                    name="Charlie",
                    age=35,
                    profile=Profile(city="Isfahan", street="four"),
                )
            )

        assert uow.is_active is False
        assert await db.repository(User).count() == 0
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_committed_row_visibility(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        await db.repository(User).create(
            _u(
                "v1",
                "visible",
                name="Visible",
                age=1,
                profile=Profile(city="Tabriz", street="five"),
            )
        )
        assert await db.repository(User).count() == 1
        rows = (
            await db.repository(User)
            .query(User.username == "visible")
            .include(User.profile)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].name == "Visible"
        assert rows[0].profile.city == "Tabriz"
        assert rows[0].profile.street == "five"
        assert adapter._in_active_transaction() is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_uow_rollback_and_transaction_commit(kind):
    db = await database_for(kind)
    adapter = db.adapter("primary")
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        async with db.unit_of_work() as uow:
            await uow.repository(User).create(
                _u(
                    "u1",
                    "bob",
                    name="Bob",
                    age=40,
                    profile=Profile(city="Mashhad", street="six"),
                )
            )
        assert transaction_calls == [None]
        assert await db.repository(User).count() == 0

        async with db.transaction():
            await db.repository(User).create(
                _u(
                    "o1",
                    "outer",
                    name="Outer",
                    age=50,
                    profile=Profile(city="Yazd", street="seven"),
                )
            )

        assert transaction_calls == [None, None]
        rows = (
            await db.repository(User)
            .query(User.username == "outer")
            .include(User.profile)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].name == "Outer"
        assert rows[0].profile.city == "Yazd"
    finally:
        await cleanup(db)


# --- Nested transactions / no-transaction block ---------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_no_transaction_reports_inactive(kind):
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    assert adapter._in_active_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_marker_set_reports_active(kind):
    from tests.db._conformance import adapter_for

    adapter = adapter_for(kind)
    adapter._tx_session = object()
    try:
        assert adapter._in_active_transaction() is True
    finally:
        adapter._tx_session = None
    assert adapter._in_active_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_lone_mutation_auto_commits_without_transaction(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        assert adapter._in_active_transaction() is False

        await db.repository(User).create(
            _u(
                "auto",
                "auto",
                name="Auto",
                age=1,
                profile=Profile(city="Kerman", street="eight"),
            )
        )
        assert await db.repository(User).count() == 1
        assert await db.repository(User).exists(User.username == "auto") is True
        assert adapter._in_active_transaction() is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_transaction_not_supported(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)

        async with db.transaction():
            assert adapter._in_active_transaction() is True
            await repo.create(
                _u("outer", "outer", age=1, profile=Profile(city="Arak", street="nine"))
            )

            with pytest.raises(Exception):
                async with db.transaction():
                    await repo.create(_u("inner", "inner", age=2))

            assert adapter._in_active_transaction() is True

        assert adapter._in_active_transaction() is False
        assert await repo.exists(User.username == "outer") is True
        assert await repo.exists(User.username == "inner") is False
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_transaction_outer_survives_rejection(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)

        async with db.transaction():
            await repo.create(
                _u(
                    "persist",
                    "persist",
                    age=1,
                    profile=Profile(city="Rasht", street="ten"),
                )
            )
            try:
                async with db.transaction():
                    await repo.create(_u("inner-fail", "inner-fail", age=2))
            except Exception:
                pass

            assert adapter._in_active_transaction() is True
            await repo.create(_u("after-fail", "after-fail", age=3))

        assert adapter._in_active_transaction() is False
        usernames = {u.username for u in await repo.query().all()}
        assert usernames == {"persist", "after-fail"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_in_transaction_error(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        repo = db.repository(User)
        await repo.create(
            _u("persist", "persist", age=1, profile=Profile(city="Rasht", street="ten"))
        )
        with pytest.raises(ValueError, match="Simulated transfer failure"):
            async with db.transaction():
                await repo.query(User.profile.city == "Rasht").update(
                    {"name": "Ali"}
                )
                u1 = await repo.query(User.profile.city == "Rasht").first()
                assert u1.name == "Ali"
                raise ValueError("Simulated transfer failure")

        assert adapter._in_active_transaction() is False
        rolled_back = await repo.query(User.username == "persist").first()
        assert rolled_back is not None
        assert rolled_back.name is None
        usernames = {u.username for u in await repo.query().all()}
        assert usernames == {"persist"}
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_in_transaction_read(kind):
    db = await database_for(kind)
    try:
        adapter = db.adapter("primary")
        transaction_calls: list[None] = []
        original_factory = adapter.transaction_factory

        def transaction_factory():
            transaction_calls.append(None)
            return original_factory()

        adapter.transaction_factory = transaction_factory
        repo = db.repository(User)
        await repo.create(
            _u("persist", "persist", age=1, profile=Profile(city="Rasht", street="ten"))
        )
        assert transaction_calls == []
        async with db.transaction():
            assert transaction_calls == [None]
            u1 = await repo.query(User.profile.city == "Rasht").update({"name": "Ali"})
            u1 = await repo.query(User.profile.city == "Rasht").first()
            assert u1.name == "Ali"

        assert adapter._in_active_transaction() is False
        assert transaction_calls == [None]
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_duplicate_key_translation(kind):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create(_u("dup", "dup", age=1))
        with pytest.raises(DuplicateKeyError):
            await repo.create(_u("dup", "dup", age=2))
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_connect_is_idempotent(kind):
    """Calling ``connect()`` twice must be a safe no-op on an open pool."""
    from tests.db._conformance import adapter_for, cleanup_adapter

    adapter = adapter_for(kind)
    await adapter.connect()
    await adapter.connect()
    assert await adapter.health_check() is True
    if kind in {"mysql", "mongodb"}:
        await cleanup_adapter(adapter)
    else:
        await adapter.disconnect()
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_reconnect_after_disconnect(kind):
    """A pool torn down by ``disconnect()`` can be re-established by ``connect()``."""
    from tests.db._conformance import adapter_for, cleanup_adapter

    adapter = adapter_for(kind)
    await adapter.connect()
    assert await adapter.health_check() is True
    await adapter.disconnect()
    assert await adapter.health_check() is False

    await adapter.connect()
    assert await adapter.health_check() is True
    if kind in {"mysql", "mongodb"}:
        await cleanup_adapter(adapter)
    else:
        await adapter.disconnect()
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_context_manager(kind):
    """Using ``Database`` as an async context manager releases the pool on exit."""
    from tests.db._conformance import adapter_for, cleanup_adapter

    adapter = adapter_for(kind)
    async with Database(adapter):
        assert await adapter.health_check() is True
    if kind in {"mysql", "mongodb"}:
        await cleanup_adapter(adapter)
    assert await adapter.health_check() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_connection_pool_shared_across_repositories(kind):
    """Repositories on one ``Database`` share the same pooled connection."""
    db = await database_for(kind)
    try:
        await db.repository(User).create(_u("cp_shared", "cp_shared", age=7))
        observed = await db.repository(User).where(User.username == "cp_shared").all()
        assert len(observed) == 1
        assert observed[0].age == 7

        count = await db.repository(User).where(User.username == "cp_shared").count()
        assert count == 1
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Backup & restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_backup_and_restore_roundtrip_all_tables(kind, tmp_path):
    db = await database_for(kind)
    try:
        repo = db.repository(User)
        await repo.create(
            _u(
                "b1",
                "b1",
                name="Backy",
                age=31,
                profile=Profile(
                                    city="Tehran",
                                    street="main",
                                    contact=Contact(phone="123456789", version=Version(name="contact-v1")),
                                    version=Version(name="profile-v1"),
                                ),
            )
        )
        await repo.create(
            _u(
                "b2",
                "b2",
                name="Resty",
                age=32,
                profile=Profile(city="Shiraz", street="second"),
            )
        )
        await db.repository(Post).create(_p("bp1", "backup post", "b1"))

        backup_path = str(tmp_path / "backup")
        counts = await db.backup(path=backup_path)

        assert counts["users"] == 2
        assert counts["posts"] == 1
        ls = ["users.json", "posts.json"]

        for name in ls:
            assert os.path.exists(os.path.join(backup_path, name)), (
                f"missing backup {name}"
            )

        # A stray row added after the backup must be discarded on restore
        # because ``restore`` drops existing rows before re-importing.
        await repo.create(_u("b_extra", "b_extra", age=99))

        restored = await db.restore(path=backup_path)
        assert restored["users"] == 2
        assert restored["posts"] == 1


        usernames = {u.username for u in await repo.query().all()}
        assert usernames == {"b1", "b2"}

        rows = await repo.query(User.username == "b1").include(User.profile).all()
        assert len(rows) == 1
        b1 = rows[0]
        assert b1.name == "Backy"
        assert b1.age == 31
        assert b1.profile.city == "Tehran"

        posts = await db.repository(Post).where(Post.user_id == "b1").all()
        assert len(posts) == 1
        assert posts[0].title == "backup post"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_backup_and_restore_selected_tables(kind, tmp_path):
    db = await database_for(kind)
    try:
        await db.repository(User).create_many(
            [_u("s1", "s1", age=1), _u("s2", "s2", age=2)]
        )
        await db.repository(Post).create(_p("sp1", "untouched", "s1"))

        backup_path = str(tmp_path / "only_users")
        counts = await db.backup(path=backup_path, tables=["users"])
        assert counts == {"users": 2}
        assert os.listdir(backup_path) == ["users.json"]

        # Restoring only ``users`` must repopulate it (dropping any extras)
        # while leaving ``posts`` alone.
        await db.repository(User).create(_u("s_extra", "s_extra", age=99))
        restored = await db.restore(path=backup_path, tables=["users"])
        assert restored == {"users": 2}

        usernames = {u.username for u in await db.repository(User).query().all()}
        assert usernames == {"s1", "s2"}

        posts = await db.repository(Post).where(Post.user_id == "s1").all()
        assert len(posts) == 1
        assert posts[0].title == "untouched"
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_restore_without_drop_existing(kind, tmp_path):
    src = await database_for(kind)
    try:
        await src.repository(User).create(_u("r1", "r1", age=1))
        backup_path = str(tmp_path / "append")
        await src.backup(path=backup_path, tables=["users"])
    finally:
        await cleanup(src)

    # A fresh database starts empty; restoring with ``drop_existing=False``
    # appends the backed-up rows into it.
    dst = await database_for(kind)
    try:
        restored = await dst.restore(
            path=backup_path, tables=["users"], drop_existing=False
        )
        assert restored == {"users": 1}
        users = await dst.repository(User).query().all()
        assert [u.username for u in users] == ["r1"]
    finally:
        await cleanup(dst)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_backup_and_restore_with_pagination(kind, tmp_path):
    db = await database_for(kind)
    try:
        await db.repository(User).create_many(
            [_u(f"pg{i:02d}", f"pg{i:02d}", age=i) for i in range(25)]
        )

        backup_path = str(tmp_path / "paginated")
        counts = await db.backup(path=backup_path, tables=["users"], page_size=10)
        assert counts == {"users": 25}

        await db.repository(User).delete_many()
        assert await db.repository(User).query().count() == 0

        restored = await db.restore(path=backup_path, tables=["users"], chunk_size=10)
        assert restored == {"users": 25}

        ages = sorted(u.age for u in await db.repository(User).query().all())
        assert ages == list(range(25))
    finally:
        await cleanup(db)


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_lifecycle(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_create_accounts.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_accounts", [
        Column("id", "str", primary_key=True),
        Column("owner", "str", nullable=False),
        Column("balance", "float", default=0.0),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_accounts")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_add_index.py").write_text(
            """async def upgrade(adapter):
    await adapter.create_index("mn_accounts", ["owner"], name="idx_mn_owner")

async def downgrade(adapter):
    await adapter.drop_index("mn_accounts", "idx_mn_owner")
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_accounts" not in await _table_names(db)

        scaffold = mm.create("add audit to accounts")
        assert scaffold.name == "0003_add_audit_to_accounts.py"
        assert scaffold.exists()
        content = scaffold.read_text(encoding="utf-8")
        assert "async def upgrade(adapter)" in content
        assert "async def downgrade(adapter)" in content

        statuses = await mm.status()
        assert len(statuses) == 3
        assert not any(s.applied for s in statuses)
        assert all(s.checksum for s in statuses)

        applied = await mm.upgrade()
        assert applied == [
            "0001_create_accounts",
            "0002_add_index",
            "0003_add_audit_to_accounts",
        ]

        statuses = await mm.status()
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)
        assert all(s.checksum for s in statuses)

        assert "mn_accounts" in await _table_names(db)

        Account = _mig_model("mn_accounts", {"owner": str, "balance": float})
        repo = db.repository(Account)
        await repo.create(Account(id="a1", owner="alice", balance=10.5))
        rows = await repo.query().all()
        assert len(rows) == 1
        assert rows[0].owner == "alice"
        assert rows[0].balance == 10.5

        assert await mm.check() is True

        reapply = await mm.upgrade()
        assert reapply == []

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_create_accounts",
            "0002_add_index",
            "0003_add_audit_to_accounts",
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_checksum_tampering(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        first = mig_dir / "0001_initial.py"
        first.write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_safe", [Column("id", "int", primary_key=True)])

async def downgrade(adapter):
    await adapter.drop_table("mn_safe")
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_safe" not in await _table_names(db)

        applied = await mm.upgrade()
        assert applied == ["0001_initial"]
        assert "mn_safe" in await _table_names(db)
        assert await mm.check() is True

        records = await mm.tracker.get_applied_migrations()
        assert [r.version for r in records] == ["0001_initial"]
        assert all(r.checksum for r in records)

        first.write_text(
            """# TAMPERED
async def upgrade(adapter):
    pass

async def downgrade(adapter):
    pass
""",
            encoding="utf-8",
        )

        with pytest.raises(MigrationChecksumError):
            await mm.check()

        with pytest.raises(MigrationChecksumError):
            await mm.upgrade()
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_downgrade_and_reset(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        for i in range(1, 4):
            (mig_dir / f"{i:04d}_step_{i}.py").write_text(
                f"""from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_step_{i}", [Column("id", "int", primary_key=True)])

async def downgrade(adapter):
    await adapter.drop_table("mn_step_{i}")
""",
                encoding="utf-8",
            )

        mm = MigrationManager(db, path=mig_dir)

        assert not {"mn_step_1", "mn_step_2", "mn_step_3"} & await _table_names(db)

        applied = await mm.upgrade()
        assert applied == ["0001_step_1", "0002_step_2", "0003_step_3"]

        names = await _table_names(db)
        assert {"mn_step_1", "mn_step_2", "mn_step_3"} <= names

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_step_1",
            "0002_step_2",
            "0003_step_3",
        }

        reverted = await mm.downgrade(1)
        assert reverted == ["0003_step_3"]

        statuses = await mm.status()
        assert statuses[0].applied
        assert statuses[1].applied
        assert not statuses[2].applied

        names = await _table_names(db)
        assert "mn_step_1" in names
        assert "mn_step_2" in names
        assert "mn_step_3" not in names

        reverted_rest = await mm.reset()
        assert reverted_rest == ["0002_step_2", "0001_step_1"]

        statuses = await mm.status()
        assert not any(s.applied for s in statuses)

        names = await _table_names(db)
        assert not {"mn_step_1", "mn_step_2", "mn_step_3"} & names

        records = await mm.tracker.get_applied_migrations()
        assert records == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_column_operations_with_data(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_base.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_cols", [
        Column("id", "str", primary_key=True),
        Column("name", "str", nullable=False),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_cols")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_add_column.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.add_column("mn_cols", Column("age", "int", default=18))

async def downgrade(adapter):
    await adapter.drop_column("mn_cols", "age")
""",
            encoding="utf-8",
        )

        (mig_dir / "0003_rename_column.py").write_text(
            """async def upgrade(adapter):
    await adapter.rename_column("mn_cols", "name", "full_name")

async def downgrade(adapter):
    await adapter.rename_column("mn_cols", "full_name", "name")
""",
            encoding="utf-8",
        )

        (mig_dir / "0004_drop_column.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.drop_column("mn_cols", "full_name")

async def downgrade(adapter):
    await adapter.add_column("mn_cols", Column("full_name", "str", nullable=True))
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_cols" not in await _table_names(db)

        assert await mm.upgrade(target="0001") == ["0001_base"]
        assert "mn_cols" in await _table_names(db)

        Base = _mig_model("mn_cols", {"name": str})
        repo = db.repository(Base)
        await repo.create(Base(id="r1", name="Alice"))
        before = await repo.query().all()
        assert len(before) == 1
        assert before[0].name == "Alice"

        assert await mm.upgrade(target="0002") == ["0002_add_column"]
        WithAge = _mig_model("mn_cols", {"name": str, "age": int})
        rows = await db.repository(WithAge).query().all()
        assert len(rows) == 1
        assert rows[0].name == "Alice"
        assert rows[0].age == 18

        assert await mm.upgrade(target="0003") == ["0003_rename_column"]
        Renamed = _mig_model("mn_cols", {"full_name": str, "age": int})
        rows = await db.repository(Renamed).query().all()
        assert len(rows) == 1
        assert rows[0].full_name == "Alice"
        assert rows[0].age == 18

        assert await mm.upgrade(target="0004") == ["0004_drop_column"]
        Dropped = _mig_model(
            "mn_cols",
            {
                "age": int,
                "full_name": str,
            },
        )
        rows = await db.repository(Dropped).query().all()
        assert len(rows) == 1
        assert rows[0].age == 18
        assert rows[0].full_name == ""

        statuses = await mm.status()
        assert len(statuses) == 4
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_base",
            "0002_add_column",
            "0003_rename_column",
            "0004_drop_column",
        }

        reverted = await mm.reset()
        assert len(reverted) == 4
        assert "mn_cols" not in await _table_names(db)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_drop_and_rename_table_with_data(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_people.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_people", [
        Column("id", "str", primary_key=True),
        Column("name", "str", nullable=False),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_people")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_rename_table.py").write_text(
            """async def upgrade(adapter):
    await adapter.rename_table("mn_people", "mn_citizens")

async def downgrade(adapter):
    await adapter.rename_table("mn_citizens", "mn_people")
""",
            encoding="utf-8",
        )

        (mig_dir / "0003_drop_table.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.drop_table("mn_citizens")

async def downgrade(adapter):
    await adapter.create_table("mn_citizens", [
        Column("id", "str", primary_key=True),
        Column("name", "str", nullable=False),
    ])
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert not {"mn_people", "mn_citizens"} & await _table_names(db)

        assert await mm.upgrade(target="0001") == ["0001_people"]
        assert "mn_people" in await _table_names(db)

        People = _mig_model("mn_people", {"name": str})
        repo = db.repository(People)
        await repo.create_many(
            [People(id="p1", name="Alice"), People(id="p2", name="Bob")]
        )
        before = await repo.query().all()
        assert len(before) == 2
        assert {r.name for r in before} == {"Alice", "Bob"}

        assert await mm.upgrade(target="0002") == ["0002_rename_table"]
        assert "mn_people" not in await _table_names(db)
        assert "mn_citizens" in await _table_names(db)

        Citizens = _mig_model("mn_citizens", {"name": str})
        after_rename = await db.repository(Citizens).query().all()
        assert len(after_rename) == 2
        assert {r.name for r in after_rename} == {"Alice", "Bob"}

        assert await mm.upgrade(target="0003") == ["0003_drop_table"]
        assert "mn_citizens" not in await _table_names(db)

        statuses = await mm.status()
        assert len(statuses) == 3
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_people",
            "0002_rename_table",
            "0003_drop_table",
        }

        reverted = await mm.reset()
        assert len(reverted) == 3
        assert not {"mn_people", "mn_citizens"} & await _table_names(db)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_migration_create_and_drop_index_with_data(kind, tmp_path: Path):
    db = await database_for(kind)
    try:
        mig_dir = tmp_path / "migrations"
        mig_dir.mkdir()

        (mig_dir / "0001_items.py").write_text(
            """from renus.db.migrations import Column

async def upgrade(adapter):
    await adapter.create_table("mn_items", [
        Column("id", "str", primary_key=True),
        Column("email", "str", nullable=False),
    ])

async def downgrade(adapter):
    await adapter.drop_table("mn_items")
""",
            encoding="utf-8",
        )

        (mig_dir / "0002_create_index.py").write_text(
            """async def upgrade(adapter):
    await adapter.create_index("mn_items", ["email"], unique=True, name="idx_mn_email")

async def downgrade(adapter):
    await adapter.drop_index("mn_items", "idx_mn_email")
""",
            encoding="utf-8",
        )

        (mig_dir / "0003_drop_index.py").write_text(
            """async def upgrade(adapter):
    await adapter.drop_index("mn_items", "idx_mn_email")

async def downgrade(adapter):
    await adapter.create_index("mn_items", ["email"], unique=True, name="idx_mn_email")
""",
            encoding="utf-8",
        )

        mm = MigrationManager(db, path=mig_dir)

        assert "mn_items" not in await _table_names(db)

        assert await mm.upgrade(target="0001") == ["0001_items"]
        assert "mn_items" in await _table_names(db)

        Item = _mig_model("mn_items", {"email": str})
        repo = db.repository(Item)
        await repo.create_many(
            [Item(id="i1", email="a@x.com"), Item(id="i2", email="b@x.com")]
        )
        before = await repo.query().all()
        assert len(before) == 2
        assert {i.email for i in before} == {"a@x.com", "b@x.com"}

        assert await mm.upgrade(target="0002") == ["0002_create_index"]
        after_create = await repo.query().all()
        assert len(after_create) == 2
        assert {i.email for i in after_create} == {"a@x.com", "b@x.com"}

        assert await mm.upgrade(target="0003") == ["0003_drop_index"]
        after_drop = await repo.query().all()
        assert len(after_drop) == 2
        assert {i.email for i in after_drop} == {"a@x.com", "b@x.com"}

        statuses = await mm.status()
        assert len(statuses) == 3
        assert all(s.applied for s in statuses)
        assert all(s.applied_at is not None for s in statuses)

        records = await mm.tracker.get_applied_migrations()
        assert {r.version for r in records} == {
            "0001_items",
            "0002_create_index",
            "0003_drop_index",
        }
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
@pytest.mark.parametrize(
    "identity_name",
    ["str", "int", "ObjectId", "Custom", "UUID"],
)
async def test_configured_identity_roundtrip_and_storage(kind, identity_name):
    """Configured IDs round-trip and use each adapter's physical representation."""
    if identity_name == "ObjectId":
        from bson import ObjectId

        identity_config = ObjectId
        expected_type = ObjectId
    elif identity_name == "UUID":
        identity_config = UUID
        expected_type = UUID
    elif identity_name == "int":
        identity_config = int
        expected_type = int
    elif identity_name == "str":
        identity_config = str
        expected_type = str
    else:
        class CustomIdentity:
            _counter = 0

            def __init__(self, value=None):
                if value is None:
                    type(self)._counter += 1
                    value = f"custom-{type(self)._counter}"
                self.value = str(value)

            def __str__(self):
                return self.value

        identity_config = CustomIdentity
        expected_type = CustomIdentity

    previous_config = Config._cache.get("database")
    Config._cache["database"] = SimpleNamespace(ID=identity_config)
    db = None
    try:
        class ConfiguredIdentityRecord(Model):
            id: ID = Field(
                default_factory=ID,
                database=DatabaseField(
                    primary_key=True,
                    generated=True
                ),
            )
            value: str

        db = Database(adapter_for(kind))
        await db.connect()
        await db.create_schema([ConfiguredIdentityRecord])
        repository = db.repository(ConfiguredIdentityRecord)

        record = await repository.create(ConfiguredIdentityRecord(value="portable"))
        assert isinstance(record.id, ID)
        assert isinstance(record.id.value, expected_type)

        fetched = await repository.where(
            ConfiguredIdentityRecord.id == record.id
        ).first()
        assert fetched is not None
        assert isinstance(fetched.id, ID)
        assert isinstance(fetched.id.value, expected_type)
        assert str(fetched.id) == str(record.id)
        assert fetched.value == "portable"

       
    finally:
        if db is not None:
            await cleanup(db)
        if previous_config is None:
            Config._cache.pop("database", None)
        else:
            Config._cache["database"] = previous_config


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_auto_generates_identity_object_id(kind, monkeypatch):
    from bson import ObjectId

    from tests.db._conformance import adapter_for

    monkeypatch.setitem(Config._cache, "database", SimpleNamespace(ID=ObjectId))

    class User(Model):
        id: ID = Field(
            default_factory=ID,
            database=DatabaseField(primary_key=True, generated=True),
        )
        name: str
        p_id: ID = Field(default=ID(), database=DatabaseField(generated=False))
        token: UUID = Field(default_factory=uuid4, database=DatabaseField(generated=True))

    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema([User])
    try:
        user = await db.repository(User).create(User(name="smko"))
        assert isinstance(user.id, ID)
        assert isinstance(user.p_id, ID)
        assert isinstance(user.token, UUID)

        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched is not None
        assert isinstance(fetched.p_id, ID)
        assert isinstance(fetched.token, UUID)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_auto_generates_identity_str(kind, monkeypatch):
    from tests.db._conformance import adapter_for

    monkeypatch.setitem(Config._cache, "database", SimpleNamespace(ID=str))

    class User(Model):
        id: ID = Field(
            default_factory=ID,
            database=DatabaseField(primary_key=True, generated=True),
        )
        name: str
        p_id: ID = Field(default=ID(), database=DatabaseField(generated=False))
        token: UUID = Field(default_factory=uuid4, database=DatabaseField(generated=True))

    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema([User])
    try:
        user = await db.repository(User).create(User(name="smko"))
        assert isinstance(user.id, ID)
        assert isinstance(user.p_id, ID)
        assert isinstance(user.token, UUID)

        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched is not None
        assert isinstance(fetched.p_id, ID)
        assert isinstance(fetched.token, UUID)
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_create_auto_generates_identity_int(kind, monkeypatch):
    from tests.db._conformance import adapter_for

    monkeypatch.setitem(Config._cache, "database", SimpleNamespace(ID=int))

    class User(Model):
        id: ID = Field(
            database=DatabaseField(primary_key=True, generated=True, auto_inc=True)
        )
        name: str
        p_id: ID = Field(default=ID(2), database=DatabaseField(generated=False))
        token: UUID = Field(default_factory=uuid4, database=DatabaseField(generated=True))

    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema([User])
    try:
        user = await db.repository(User).create(User(name="smko"))
        assert isinstance(user.id, ID)
        assert isinstance(user.p_id, ID)
        assert isinstance(user.token, UUID)
        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched.id.value == 1
        user = await db.repository(User).create(User(name="smko"))
        fetched = await db.repository(User).where(User.id == user.id).first()
        assert fetched is not None
        assert isinstance(fetched.p_id, ID)
        assert isinstance(fetched.token, UUID)
        assert fetched.id.value == 2
    finally:
        await cleanup(db)


@pytest.mark.parametrize("kind", ADAPTERS)
def test_auto_inc_requires_primary_key(kind, monkeypatch):
    monkeypatch.setitem(Config._cache, "database", SimpleNamespace(ID=int))

    with pytest.raises(ValueError, match="auto_inc=True must be primary_key=True"):

        class InvalidView(Model):
            id: str = Field(database=DatabaseField(primary_key=True))
            views: int = Field(database=DatabaseField(generated=True, auto_inc=True))


def test_auto_inc_requires_integer_field():
    from renus.db.mongodb.compiler import MongoCompiler
    from renus.db.mutation import Insert

    class InvalidView(Model):
        id: str = Field(
            database=DatabaseField(primary_key=True, generated=True, auto_inc=True)
        )

    with pytest.raises(ValueError, match="must have type int or ID"):
        MongoCompiler().compile_mutation(Insert(InvalidView, {}))


def test_auto_inc_requires_integer_config(monkeypatch):
    from renus.db.mongodb.compiler import MongoCompiler
    from renus.db.mutation import Insert

    monkeypatch.setitem(Config._cache, "database", SimpleNamespace(ID=str))

    class InvalidConfigView(Model):
        id: ID = Field(
            database=DatabaseField(primary_key=True, generated=True, auto_inc=True)
        )

    with pytest.raises(ValueError, match=r"Config\('database'\)\.ID=int"):
        MongoCompiler().compile_mutation(Insert(InvalidConfigView, {}))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_single_table_create_does_not_start_transaction(kind):
    from tests.db._conformance import adapter_for

    class PlainRecord(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        name: str

    adapter = adapter_for(kind)
    db = Database(adapter)
    await db.connect()
    await db.create_schema([PlainRecord])
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        await db.repository(PlainRecord).create(
            PlainRecord(id="plain-1", name="single table")
        )
        assert transaction_calls == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_relationship_create_starts_transaction_only_for_multiple_tables(kind):
    from tests.db._conformance import adapter_for

    class RelatedRecord(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        name: str
        profile: Profile

    adapter = adapter_for(kind)
    db = Database(adapter)
    await db.connect()
    await db.create_schema([RelatedRecord])
    transaction_calls: list[None] = []
    original_factory = adapter.transaction_factory

    def transaction_factory():
        transaction_calls.append(None)
        return original_factory()

    adapter.transaction_factory = transaction_factory
    try:
        await db.repository(RelatedRecord).create(
            RelatedRecord(
                id="related-1",
                name="relationship",
                profile=Profile(city="Tehran", street="one"),
            )
        )
        assert transaction_calls == []
    finally:
        await cleanup(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_scalar_type_roundtrips_and_sql_text_length(kind):
    """Exercise long text, bounded text, decimals, and custom values everywhere."""

    class CustomValue:
        def __init__(self, value: str):
            self.value = value

        def __str__(self) -> str:
            return self.value

        def __eq__(self, other: object) -> bool:
            return isinstance(other, CustomValue) and self.value == other.value

    class ScalarTypes(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        short_text: str = Field(MaxLen(80))
        long_text: str = Field(MaxLen(1000))
        amount: Decimal
        custom: CustomValue

    db = await database_for(kind, [ScalarTypes])
    try:
        meta = ScalarTypes.metadata()
        dialect = getattr(db.adapter("primary"), "dialect", None)
        if dialect is not None and hasattr(dialect, "type_to_sql"):
            assert dialect.type_to_sql(meta.fields["short_text"]) == "VARCHAR(80)"
            assert dialect.type_to_sql(meta.fields["long_text"]) == (
                "LONGTEXT" if kind == "mysql" else "TEXT"
            )

        value = ScalarTypes(
            id="scalar-1",
            short_text="bounded",
            long_text="x" * 512,
            amount=Decimal("1234567890.1234"),
            custom=CustomValue("custom-value"),
        )
        await db.repository(ScalarTypes).create(value)
        fetched = await db.repository(ScalarTypes).where(ScalarTypes.id == "scalar-1").first()

        assert fetched is not None
        assert fetched.short_text == "bounded"
        assert fetched.long_text == "x" * 512
        assert fetched.amount == Decimal("1234567890.1234")
        assert fetched.custom == CustomValue("custom-value")
    finally:
        await cleanup(db)


class TableWithEmbedded(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    settings: dict[str, str]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_search_matches_values_in_embedded_dictionary_paths(kind):
    async def setup():
        database = await database_for(kind, [TableWithEmbedded])
        repository = database.repository(TableWithEmbedded)
        await repository.create(
            TableWithEmbedded(
                id="1",
                name="first",
                settings={"en": "Hello world", "fa": "Salam", "code": "alpha"},
            )
        )
        await repository.create(
            TableWithEmbedded(
                id="2",
                name="second",
                settings={"en": "Good morning", "fa": "صبح بخیر", "code": "bravo"},
            )
        )
        await repository.create(
            TableWithEmbedded(
                id="3",
                name="third",
                settings={"en": "Good morning", "fa": "صبح زیبا", "code": "charlie"},
            )
        )
        await repository.create(
            TableWithEmbedded(
                id="4",
                name="fourth",
                settings={"en": "Good evening", "fa": "سلام"},
            )
        )
        return database, repository

    database, repository = await setup()
    try:
        results = await repository.where(
            TableWithEmbedded.settings.fa.like("%صبح%")
        ).order_by(TableWithEmbedded.id.asc()).all()
        assert len(results) == 2
        assert results[0].settings["fa"] == "صبح بخیر"
        assert results[1].settings["fa"] == "صبح زیبا"
        assert await repository.where(
            TableWithEmbedded.settings.fa.like("%صبح%")
        ).count() == 2

        async def matching_ids(condition):
            return [
                row.id
                for row in await repository.where(condition)
                .order_by(TableWithEmbedded.id.asc())
                .all()
            ]

        code = TableWithEmbedded.settings.code
        assert await matching_ids(code == "bravo") == ["2"]
        assert await matching_ids(code != "bravo") == ["1", "3", "4"]
        assert await matching_ids(code > "bravo") == ["3"]
        assert await matching_ids(code >= "bravo") == ["2", "3"]
        assert await matching_ids(code < "bravo") == ["1"]
        assert await matching_ids(code <= "bravo") == ["1", "2"]
        assert await matching_ids(code.in_(["alpha", "charlie"])) == ["1", "3"]
        assert await matching_ids(code.not_in(["alpha", "charlie"])) == ["2", "4"]
        assert await matching_ids(TableWithEmbedded.settings.missing.is_null()) == [
            "1", "2", "3", "4"
        ]
        assert await matching_ids(code.is_not_null()) == ["1", "2", "3"]
        assert await matching_ids(code.like("%li%")) == ["3"]
        assert await matching_ids(code.regex(r"^b.*o$")) == ["2"]
        assert await matching_ids(code.between("bravo", "charlie")) == ["2", "3"]
        assert await matching_ids((code >= "bravo") & (code < "charlie")) == ["2"]
        assert await matching_ids((code == "alpha") | (code == "charlie")) == [
            "1", "3"
        ]
        assert await matching_ids(~(code == "bravo")) == ["1", "3", "4"]
    finally:
        await cleanup(database)



class TableUser(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    roles :list[ID]
    
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_list_id(kind):
    database = await database_for(kind, [TableUser])
    
    try:

        role_id=ID(1)
        repository = database.repository(TableUser)
        user = TableUser(id="1", name="first", roles=[role_id])
        await repository.create(user)
        result = await repository.where(TableUser.id == "1").first()
        assert result.roles == [role_id]
        result = await repository.where(TableUser.roles.in_(role_id)).first()
        assert result.roles == [role_id]
        
    finally:
        await cleanup(database)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_list_str(kind):
    class Order(Model):
        id: int
        items: list


    database = await database_for(kind, [Order])
    
    try:
        repository = database.repository(Order)
        Order(id=100, items=["q", "r", 3])
        await repository.create(Order(id=100, items=["q", "r"]))
        result = await repository.where(Order.id == 100).first()
        assert result.items == ["q", "r"]

        
    finally:
        await cleanup(database)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_list_int(kind):
    class NumberList(Model):
        id: int
        values: list[int]

    database = await database_for(kind, [NumberList])
    try:
        with pytest.raises(ValidationError):
            NumberList(id=100, values=["q", "r", 3])
        repository = database.repository(NumberList)
        await repository.create(NumberList(id=101, values=[1, 2, 3]))
        result = await repository.where(NumberList.id == 101).first()
        assert result.values == [1, 2, 3]
        assert all(type(value) is int for value in result.values)
    finally:
        await cleanup(database)

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_object_id(kind):
    previous_config = Config._cache.get("database")
    Config._cache["database"] = SimpleNamespace(ID=ObjectId)
    database = None
    try:
        class User(Model):
            id: ID
            name: str

        database = await database_for(kind, [User])
        user_id = ID(ObjectId())
        repository = database.repository(User)
        await repository.create(User(id=user_id, name="smko"))
        result = await repository.where(User.id == user_id).first()
        assert result.id == user_id
        assert isinstance(result.id.value, ObjectId)
        assert result.name == "smko"

        adapter = database.adapter("primary")
        metadata = User.__db_metadata__
        if kind == "mongodb":
            document = await adapter._mongo_db[metadata.table].find_one(
                {"_id": user_id.value}
            )
            assert document is not None
            assert isinstance(document["_id"], ObjectId)
        elif kind == "sqlite":
            primary_key = metadata.fields[metadata.primary_key_field]
            row = adapter._sqlite_db.execute(
                f'SELECT "{primary_key.column_name}" FROM "{metadata.table}"'
            ).fetchone()
            assert row is not None
            assert isinstance(row[primary_key.column_name], str)
            assert row[primary_key.column_name] == str(user_id.value)
    finally:
        if database is not None:
            await cleanup(database)
        if previous_config is None:
            Config._cache.pop("database", None)
        else:
            Config._cache["database"] = previous_config


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_list_item(kind):
    class Item(Model):
        name: str
        quantity: int

    class Order(Model):
        id: int
        items: list[Item]

    order = Order(
        id=100,
        items=[{"name": "Apple", "quantity": 3}, {"name": "Banana", "quantity": 5}],
    )
    database = await database_for(kind, [Order,Item])
    
    try:
        repository = database.repository(Order)
        await repository.create(order)

        results = await repository.where(
            Order.id==100
        ).include(Order.items).first()
        assert len(results.items)==2
        assert results.items[0].name=="Apple"
        
    finally:
        await cleanup(database)

    
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested(kind):
    class TableUser(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        setting :dict[str,int]
        
    database = await database_for(kind, [TableUser])
    
    try:
        repository = database.repository(TableUser)
       
        await repository.create(TableUser(id="2", setting={"one":10,"two":20}))
        await repository.create(TableUser(id="1", setting={"one":1,"two":2}))
        result = await repository.where(TableUser.setting.one == 1).first()
        assert result.id == "1"
        result = await repository.where(TableUser.setting.one == 10).first()
        assert result.id == "2"
        with pytest.raises(ValidationError):
            TableUser(id="3", setting={"one":"1","two":2})

        with pytest.raises(ValidationError):
            TableUser(id="3", setting={1:1,"two":2})
            
    finally:
        await cleanup(database)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_deep(kind):
    class TableUser(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        setting :dict

    database = await database_for(kind, [TableUser])

    try:
        repository = database.repository(TableUser)

        await repository.create(TableUser(id="1", setting={
            "one":{"d":"alpha"},
            "two":2}))
        await repository.create(TableUser(id="2", setting={
            "one":{"d":"bravo", "c":["test", "test2"]},
            "two":2}))
        await repository.create(TableUser(id="3", setting={
            "one":{"d":"charlie", "c":["other"]},
            "two":3}))
        await repository.create(TableUser(id="4", setting={
            "one":{"d":None},
            "two":4}))

        async def matching_ids(condition):
            return [
                row.id
                for row in await repository.where(condition)
                .order_by(TableUser.id.asc())
                .all()
            ]

        value = TableUser.setting.one.d
        assert await matching_ids(value == "bravo") == ["2"]
        assert await matching_ids(value != "bravo") == ["1", "3", "4"]
        assert await matching_ids(value > "bravo") == ["3"]
        assert await matching_ids(value >= "bravo") == ["2", "3"]
        assert await matching_ids(value < "bravo") == ["1"]
        assert await matching_ids(value <= "bravo") == ["1", "2"]
        assert await matching_ids(value.in_(["alpha", "charlie"])) == ["1", "3"]
        assert await matching_ids(value.not_in(["alpha", "charlie"])) == ["2", "4"]
        assert await matching_ids(value.is_null()) == ["4"]
        assert await matching_ids(value.is_not_null()) == ["1", "2", "3"]
        assert await matching_ids(value.like("%ha%")) == ["1", "3"]
        assert await matching_ids(value.regex(r"^b.*o$")) == ["2"]
        assert await matching_ids(value.between("bravo", "charlie")) == ["2", "3"]
        assert await matching_ids((value >= "bravo") & (value < "delta")) == [
            "2", "3"
        ]
        assert await matching_ids((value == "alpha") | (value == "charlie")) == [
            "1", "3"
        ]
        assert await matching_ids(~(value == "bravo")) == ["1", "3", "4"]
        assert await matching_ids(TableUser.setting.one.missing.is_null()) == [
            "1", "2", "3", "4"
        ]

        array_value = TableUser.setting.one.c
        assert await matching_ids(array_value.in_("test")) == ["2"]
        assert await matching_ids(array_value.in_(["test2", "other"])) == [
            "2", "3"
        ]
        assert await matching_ids(array_value.not_in("test")) == ["1", "3", "4"]
        assert await repository.where(value >= "bravo").count() == 2
        assert await repository.where(value == "charlie").exists()

    finally:
        await cleanup(database)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ADAPTERS)
async def test_nested_deep_list(kind):
    class TableUser(Model):
        id: str = Field(database=DatabaseField(primary_key=True))
        setting: dict

    database = await database_for(kind, [TableUser])

    try:
        repository = database.repository(TableUser)
        await repository.create_many(
            [
                TableUser(
                    id="1",
                    setting={"outer": {"middle": {"items": ["alpha", "beta"]}}},
                ),
                TableUser(
                    id="2",
                    setting={"outer": {"middle": {"items": ["gamma"]}}},
                ),
                TableUser(
                    id="3",
                    setting={"outer": {"middle": {"items": []}}},
                ),
                TableUser(id="4", setting={"outer": {"middle": {}}}),
            ]
        )

        async def matching_ids(condition):
            return [
                row.id
                for row in await repository.where(condition)
                .order_by(TableUser.id.asc())
                .all()
            ]

        items = TableUser.setting.outer.middle.items
        assert await matching_ids(items.in_("alpha")) == ["1"]
        assert await matching_ids(items.in_(["beta", "gamma"])) == ["1", "2"]
        assert await matching_ids(items.not_in("alpha")) == ["2", "3", "4"]
        assert await matching_ids(items.is_null()) == ["4"]
        assert await matching_ids(items.is_not_null()) == ["1", "2", "3"]
        assert await matching_ids(getattr(items, "0") == "alpha") == [
            "1"
        ]
    finally:
        await cleanup(database)
