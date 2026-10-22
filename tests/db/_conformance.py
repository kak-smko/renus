from __future__ import annotations

from renus.db.validation import Max

"""Adapter conformance interface (the "test interface every adapter must pass").

This module defines the *contract* a database adapter must honour to be
considered correctly implemented, plus the machinery to run the conformance
suite against any adapter without touching the tests themselves.

To make a new adapter part of the conformance suite simply register a driver::

    from renus.db import Database
    from tests.db._conformance import AdapterDriver, register_adapter_driver

    class MyAdapterDriver(AdapterDriver):
        kind = "my_backend"
        label = "MyDB"

        def make_adapter(self):
            return MyAdapter({...})

        @staticmethod
        def ready() -> bool:
            return True

    register_adapter_driver(MyAdapterDriver())

Once registered, every conformance test in ``test_adapter_conformance.py``
runs against that backend. If the adapter passes the whole suite it is, by
definition, correctly implemented for the standard operations Renus exposes.
"""

import os
import uuid
from abc import ABC, abstractmethod
from typing import Any

import pytest

from renus.db import (
    Database,
    DatabaseField,
    Field,
    ManyToMany,
    ManyToOne,
    OneToMany,
    OneToOne,
    Model,
    Reference,
)
from renus.db.mongodb import MongoDBAdapter
from renus.db.mysql import MySQLAdapter
from renus.db.sqlite import SQLiteAdapter

__all__ = [
    "AdapterDriver",
    "CONFORMANCE_ADAPTERS",
    "register_adapter_driver",
    "unregister_adapter_driver",
    "conformance_tests",
    "adapter_for",
    "database_for",
    "cleanup",
    "Profile",
    "User",
    "Post",
    "SoftUser",
    "Tag",
    "Passport",
    "Dept",
    "Citizen",
    "Item",
    "Employee",
]


# ---------------------------------------------------------------------------
# Standard models exercised by every conformance test.
# ---------------------------------------------------------------------------
class Version(Model):
    name:str="1"

class Contact(Model):
    phone: str
    version: Version | None = None
    
class Profile(Model):
    street: str
    city: str
    contact: Contact | None = None
    version: Version | None = None

class Post(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    title: str
    user_id: str = ""


class User(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    username: str = Field(database=DatabaseField(unique=True))
    name: str | None = None
    age: int =Field(Max(120),default=0)
    active: bool = True
    profile: Profile | None = Field(default=None)
    posts: list[Post] = OneToMany(
        Post, foreign_key="user_id", on_save="cascade", on_delete="cascade"
    )

    class Meta:
        timestamps = True
        soft_delete = True


class SoftUser(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    username: str

    class Meta:
        soft_delete = True
        timestamps = True


# ---------------------------------------------------------------------------
# Relationship models: OneToOne, ManyToOne, OneToMany, ManyToMany, and Reference.
# ---------------------------------------------------------------------------

class Tag(Model):
    name: str


class Passport(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    citizen_id: str = ""
    number: str


class Dept(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str


class Role(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str


class Citizen(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    passport: Passport = OneToOne(
        Passport, foreign_key="citizen_id", on_save="cascade", on_delete="cascade"
    )


class Item(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: Profile | None = None
    tags: list[Tag] = Field(default_factory=list)


class Employee(Model):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    dept_id: str = ""
    dept: Dept = ManyToOne(Dept, foreign_key="dept_id")
    manager: Dept = Reference(Dept, foreign_key="dept_id")
    roles: list[Role] = ManyToMany(Role, through="employee_roles")


OWNER_REL = Citizen
ONE_TO_MANY_OWNER = User


# ---------------------------------------------------------------------------
# The one interface a backend must implement to join the suite.
# ---------------------------------------------------------------------------

class AdapterDriver(ABC):
    """Interface a database backend must satisfy to join the conformance suite.

    Subclasses only need to provide :attr:`kind`, :attr:`label` and implement
    :meth:`make_adapter` and :meth:`ready`.
    """

    #: Unique backend id, also used as the pytest parametrize id.
    kind: str
    #: Human-friendly label shown when a backend is unavailable.
    label: str

    @abstractmethod
    def make_adapter(self):
        """Return a fresh, unconnected adapter instance for database :attr:`kind`.

        The returned object must satisfy ``AsyncDatabaseAdapter`` and be usable
        via ``Database(adapter)``.
        """
        ...

    @staticmethod
    def ready() -> bool:
        """Return whether this backend is available in the current environment."""
        return True

    def make_database(self) -> Database:
        """Return a fresh ``Database`` wrapping a new adapter instance."""
        return Database(self.make_adapter())

    async def drop_database(self, adapter) -> None:
        """Drop the database backing the given adapter."""
        pass


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_CONFORMANCE_ADAPTERS: dict[str, AdapterDriver] = {}


def register_adapter_driver(driver: AdapterDriver) -> None:
    """Register an adapter driver so it runs the conformance suite.

    A raised conformance failure now also covers this backend; a passing suite
    is the definition of "correctly implemented".
    """
    _CONFORMANCE_ADAPTERS[driver.kind] = driver


def unregister_adapter_driver(kind: str) -> None:
    """Remove a previously registered driver."""
    _CONFORMANCE_ADAPTERS.pop(kind, None)


def all_drivers() -> list[AdapterDriver]:
    """Return all registered drivers in registration order."""
    return list(_CONFORMANCE_ADAPTERS.values())


def _mongo_ready() -> bool:
    client = None
    try:
        import pymongo

        if getattr(pymongo, "AsyncMongoClient", None) is None:
            return False

        client = pymongo.MongoClient(
            "mongodb://localhost:27017", serverSelectionTimeoutMS=1500
        )
        client.admin.command("ping")
        hello = client.admin.command("hello")
        return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")
    except Exception:
        return False
    finally:
        if client is not None:
            client.close()


def _mysql_admin_pool(config: dict[str, Any], *, connect_timeout: int | None = None):
    from renus.db.mysql.adapter import aiomysql

    if aiomysql is None:
        raise RuntimeError("aiomysql is not installed")

    return aiomysql.create_pool(
        host=str(config.get("host", "localhost")),
        port=int(config.get("port", 3306)),
        user=str(config.get("username", config.get("user", "root"))),
        password=str(config.get("password", "")),
        connect_timeout=connect_timeout or int(config.get("connect_timeout", 5)),
        minsize=1,
        maxsize=1,
    )


def _mysql_identifier(name: str) -> str:
    if not name or any(not (char.isascii() and (char.isalnum() or char == "_")) for char in name):
        raise ValueError(f"Invalid MySQL database name: {name!r}")
    return f"`{name}`"


async def _create_mysql_database(config: dict[str, Any]) -> None:
    pool = await _mysql_admin_pool(config)
    try:
        conn = await pool.acquire()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS {_mysql_identifier(str(config['database']))}"
                )
        finally:
            pool.release(conn)
    finally:
        pool.close()
        await pool.wait_closed()


def _mysql_ready() -> bool:
    import asyncio

    config = {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "connect_timeout": 2,
    }
    probe_database = _unique_db("mysql_probe")

    async def probe() -> bool:
        pool = None
        conn = None
        created = False
        try:
            pool = await _mysql_admin_pool(config, connect_timeout=2)
            conn = await pool.acquire()
            async with conn.cursor() as cur:
                await cur.execute(
                    f"CREATE DATABASE {_mysql_identifier(probe_database)}"
                )
                created = True
                await cur.execute(
                    f"DROP DATABASE {_mysql_identifier(probe_database)}"
                )
                created = False
            return True
        except Exception:
            return False
        finally:
            if conn is not None and pool is not None:
                if created:
                    try:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                f"DROP DATABASE IF EXISTS {_mysql_identifier(probe_database)}"
                            )
                    except Exception:
                        pass
                pool.release(conn)
            if pool is not None:
                pool.close()
                await pool.wait_closed()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(probe())
    return False


class _ConformanceMySQLAdapter(MySQLAdapter):
    """MySQL adapter that provisions its isolated database for test runs."""

    async def connect(self) -> None:
        if self._mysql_db is None:
            await _create_mysql_database(self.config)
        await super().connect()


def _unique_db(prefix: str) -> str:
    return f"renus_conf_{os.getpid()}_{prefix}_{uuid.uuid4().hex[:6]}"


def _drive(kind: str, label: str, factory, ready, drop_database=None) -> AdapterDriver:
    methods = {
        "kind": kind,
        "label": label,
        "make_adapter": lambda self, _f=factory: _f(),
        "ready": staticmethod(ready),
    }
    if drop_database is not None:
        methods["drop_database"] = drop_database
    return type("_CfgDriver", (AdapterDriver,), methods)()


def _builtin_drivers() -> list[AdapterDriver]:
    return [
        _drive(
            "sqlite",
            "SQLite (:memory:)",
            lambda: SQLiteAdapter({"database": ":memory:"}),
            lambda: True,
        ),
        _drive(
            "mongodb",
            "MongoDB (localhost)",
            lambda: MongoDBAdapter(
                {"uri": "mongodb://localhost:27017", "database": _unique_db("mongo")}
            ),
            _mongo_ready,
            drop_database=lambda self, adapter: _drop_mongo_database(adapter),
        ),
        _drive(
            "mysql",
            "MySQL (localhost)",
            lambda: _ConformanceMySQLAdapter(
                {
                    "host": "localhost",
                    "port": 3306,
                    "user": "root",
                    "password": "",
                    "database": _unique_db("mysql"),
                }
            ),
            _mysql_ready,
            drop_database=lambda self, adapter: _drop_mysql_database(adapter),
        ),
    ]


CONFORMANCE_ADAPTERS: list[AdapterDriver] = _builtin_drivers()

for _driver in CONFORMANCE_ADAPTERS:
    register_adapter_driver(_driver)


# ---------------------------------------------------------------------------
# Parametrization + database helpers.
# ---------------------------------------------------------------------------

def conformance_tests() -> list[Any]:
    """Return the ``@pytest.mark.parametrize`` list for all registered drivers.

    Backends that are not reachable right now (e.g. no local MongoDB/MySQL)
    are reported as *skipped* rather than failed, so any backend that *is*
    reachable is exercised wherever it is available.
    """
    result = []
    for driver in all_drivers():
        if driver.ready():
            result.append(pytest.param(driver.kind, id=driver.kind))
        else:
            result.append(
                pytest.param(
                    driver.kind,
                    id=driver.kind,
                    marks=pytest.mark.skipif(True, reason=f"{driver.label} not reachable"),
                )
            )
    return result


def adapter_for(kind: str):
    """Return a fresh, unconnected adapter for a registered kind.
    """
    return _CONFORMANCE_ADAPTERS[kind].make_adapter()


async def _drop_mongo_database(adapter) -> None:
    await adapter._mongo_client.drop_database(adapter._mongo_db.name)


async def _drop_mysql_database(adapter) -> None:
    pool = await _mysql_admin_pool(adapter.config)
    try:
        conn = await pool.acquire()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"DROP DATABASE IF EXISTS {_mysql_identifier(str(adapter.config['database']))}"
                )
        finally:
            pool.release(conn)
    finally:
        pool.close()
        await pool.wait_closed()


async def cleanup_adapter(adapter) -> None:
    driver = _CONFORMANCE_ADAPTERS[adapter.name]
    try:
        if driver.kind == "mongodb" and not await adapter.health_check():
            await adapter.connect()
        await driver.drop_database(adapter)
    finally:
        await adapter.disconnect()


async def cleanup(db: Database) -> None:
    adapter = db.adapter("primary")
    driver = _CONFORMANCE_ADAPTERS[adapter.name]
    try:
        if driver.kind == "mongodb" and not await adapter.health_check():
            await adapter.connect()
        await driver.drop_database(adapter)
    finally:
        await db.disconnect()


async def database_for(kind: str, models=None):
    """Create a connected ``Database`` with schema ready for ``models``.

    The caller is responsible for teardown via ``await cleanup(db)``.
    """
    db = Database(adapter_for(kind))
    try:
        await db.connect()
        await db.create_schema(models or [User, Post, SoftUser])
        return db
    except BaseException:
        await cleanup(db)
        raise
