from __future__ import annotations

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
    Embedded,
    EmbeddedMany,
    Field,
    ManyToMany,
    ManyToOne,
    OneToMany,
    OneToOne,
    ReModel,
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

class Profile(ReModel):
    street: str
    city: str


class Post(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    title: str
    user_id: str = ""


class User(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    username: str = Field(database=DatabaseField(unique=True))
    name: str | None = None
    age: int = 0
    active: bool = True
    profile: Profile = Embedded(Profile)
    posts: list[Post] = OneToMany(
        Post, foreign_key="user_id", on_save="cascade", on_delete="cascade"
    )

    class Meta:
        timestamps = True
        soft_delete = True


class SoftUser(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    username: str

    class Meta:
        soft_delete = True
        timestamps = True


# ---------------------------------------------------------------------------
# Relationship models: Embedded, EmbeddedMany, OneToOne, ManyToOne, OneToMany,
# ManyToMany, and Reference.
# ---------------------------------------------------------------------------

class Tag(ReModel):
    name: str


class Passport(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    citizen_id: str = ""
    number: str


class Dept(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str


class Role(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str


class Citizen(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    passport: Passport = OneToOne(
        Passport, foreign_key="citizen_id", on_save="cascade", on_delete="cascade"
    )


class Item(ReModel):
    id: str = Field(database=DatabaseField(primary_key=True))
    name: str
    address: Profile = Embedded(Profile)
    tags: list[Tag] = EmbeddedMany(Tag)


class Employee(ReModel):
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
    try:
        import pymongo

        client = pymongo.MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=1500)
        client.admin.command("ping")
        client.close()
        return True
    except Exception:
        return False


def _mysql_ready() -> bool:
    try:
        import asyncio

        import aiomysql

        async def probe() -> bool:
            try:
                pool = await aiomysql.create_pool(
                    host="localhost",
                    port=3306,
                    user="root",
                    password="",
                    connect_timeout=2,
                    minsize=1,
                    maxsize=1,
                )
                pool.close()
                await pool.wait_closed()
                return True
            except Exception:
                return False

        return asyncio.run(probe())
    except Exception:
        return False


def _unique_db(prefix: str) -> str:
    return f"renus_conf_{os.getpid()}_{prefix}_{uuid.uuid4().hex[:6]}"


def _drive(kind: str, label: str, factory, ready) -> AdapterDriver:
    driver = type(
        "_CfgDriver",
        (AdapterDriver,),
        {
            "kind": kind,
            "label": label,
            "make_adapter": lambda self, _f=factory: _f(),
            "ready": staticmethod(ready),
        },
    )()
    return driver


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
        ),
        _drive(
            "mysql",
            "MySQL (localhost)",
            lambda: MySQLAdapter(
                {
                    "host": "localhost",
                    "port": 3306,
                    "user": "root",
                    "password": "",
                    "database": _unique_db("mysql"),
                }
            ),
            _mysql_ready,
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


async def database_for(kind: str, models=None):
    """Create a connected ``Database`` with schema ready for ``models``.

    The caller is responsible for ``await db.disconnect()``.
    """
    db = Database(adapter_for(kind))
    await db.connect()
    await db.create_schema(models or [User, Post, SoftUser])
    return db
