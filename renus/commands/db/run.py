from __future__ import annotations

import asyncio
import base64
import datetime
import json
import os
from typing import Any

from renus.config import Config
from renus.db.database import Database
from renus.db.plugins.registry import get_adapter
from renus.rich import Terminal
try:
    from bson import (
        Binary,
        Code,
        DBRef,
        Decimal128,
        Int64,
        MaxKey,
        MinKey,
        ObjectId,
        Regex,
        Timestamp,
    )

    HAVE_BSON = True
except ImportError:
    HAVE_BSON = False

    class ObjectId(str):
        pass

    class Decimal128:

        def __init__(self, val: Any) -> None:
            self.val = str(val)

        def __str__(self) -> str:
            return self.val

    class Binary(bytes):

        subtype: int

        def __new__(cls, data: bytes = b"", subtype: int = 0) -> "Binary":
            instance = super().__new__(cls, data)
            instance.subtype = subtype
            return instance

    class Regex:

        pattern: str
        flags: str

        def __init__(self, pattern: str = "", flags: str = "") -> None:
            self.pattern = pattern
            self.flags = flags

    class Code(str):

        scope: Any

        def __new__(cls, code: str = "", scope: Any = None) -> "Code":
            instance = super().__new__(cls, code)
            instance.scope = scope
            return instance

    class Timestamp:

        time: int
        inc: int

        def __init__(self, time: int = 0, inc: int = 0) -> None:
            self.time = time
            self.inc = inc

    class DBRef:

        def __init__(self, collection: str, id: Any, database: str | None = None) -> None:
            self.collection = collection
            self.id = id
            self.database = database

    class Int64(int):
        pass

    class MinKey:
        pass

    class MaxKey:
        pass

DESCRIPTION = """Database management using portable DB Database facade:
  db --drop     => Delete all records in all tables
  db --backup   => Export all tables into JSON files
  db --restore  => Restore tables from JSON files
  db migrate    => create | upgrade | downgrade | status | check | reset
  Options: --path <dir>, --driver <sqlite|mysql|mongodb>, --table <table>,
           --connection <name>"""

class MongoJSONEncoder(json.JSONEncoder):
    """JSON encoder that serializes BSON/DB types to JSON literals."""

    def default(self, o: Any) -> Any:
        """Serialize a BSON object by its JSON literal mapping."""
        obj = o
        if isinstance(obj, ObjectId):
            return {"$oid": str(obj)}
        elif isinstance(obj, datetime.datetime):
            return {"$date": obj.isoformat() + "Z" if obj.tzinfo is None else obj.isoformat()}
        elif isinstance(obj, datetime.date):
            return {"$date": obj.isoformat()}
        elif isinstance(obj, Decimal128):
            return {"$numberDecimal": str(obj)}
        elif isinstance(obj, Binary):
            return {
                "$binary": {
                    "base64": base64.b64encode(obj).decode("utf-8"),
                    "subType": getattr(obj, "subtype", 0),
                }
            }
        elif isinstance(obj, Regex):
            return {
                "$regularExpression": {
                    "pattern": obj.pattern,
                    "options": getattr(obj, "flags", ""),
                }
            }
        elif isinstance(obj, Code):
            if getattr(obj, "scope", None):
                return {"$code": str(obj), "$scope": obj.scope}
            return {"$code": str(obj)}
        elif isinstance(obj, Timestamp):
            return {"$timestamp": {"t": obj.time, "i": obj.inc}}
        elif isinstance(obj, Int64):
            return {"$numberLong": str(obj)}
        elif isinstance(obj, (int, float)):
            if isinstance(obj, bool):
                return obj
            elif obj > 2**31 - 1 or obj < -(2**31):
                return {"$numberLong": str(int(obj))}
            return obj
        elif isinstance(obj, MinKey):
            return {"$minKey": 1}
        elif isinstance(obj, MaxKey):
            return {"$maxKey": 1}
        elif isinstance(obj, (bytes, bytearray)):
            return {
                "$binary": {
                    "base64": base64.b64encode(bytes(obj)).decode("utf-8"),
                    "subType": "00",
                }
            }
        elif hasattr(obj, "items"):
            return {k: self.default(v) for k, v in obj.items()}
        elif hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes)):
            return [self.default(v) for v in obj]

        return super().default(obj)

def mongo_json_decoder(obj: Any) -> Any:
    """Decode JSON literals back into BSON types."""
    if not isinstance(obj, dict):
        return obj

    if "$oid" in obj:
        return ObjectId(obj["$oid"])
    elif "$date" in obj:
        val = obj["$date"]
        try:
            if isinstance(val, str):
                return datetime.datetime.fromisoformat(val.rstrip("Z"))
            else:
                return datetime.datetime.fromtimestamp(val / 1000.0)
        except (ValueError, TypeError):
            return val
    elif "$numberDecimal" in obj:
        return Decimal128(obj["$numberDecimal"])
    elif "$binary" in obj:
        base64_str = obj["$binary"]["base64"]
        subtype = obj["$binary"].get("subType", 0)
        return Binary(base64.b64decode(base64_str), subtype)
    elif "$regularExpression" in obj:
        pattern = obj["$regularExpression"]["pattern"]
        options = obj["$regularExpression"].get("options", "")
        return Regex(pattern, options)
    elif "$code" in obj:
        if "$scope" in obj:
            return Code(obj["$code"], scope=obj["$scope"])
        return Code(obj["$code"])
    elif "$timestamp" in obj:
        return Timestamp(obj["$timestamp"]["t"], obj["$timestamp"]["i"])
    elif "$numberLong" in obj:
        return Int64(obj["$numberLong"])
    elif "$numberInt" in obj:
        return int(obj["$numberInt"])
    elif "$numberDouble" in obj:
        return float(obj["$numberDouble"])
    elif "$minKey" in obj:
        return MinKey()
    elif "$maxKey" in obj:
        return MaxKey()

    for key, value in obj.items():
        if isinstance(value, dict):
            obj[key] = mongo_json_decoder(value)
        elif isinstance(value, list):
            obj[key] = [mongo_json_decoder(item) for item in value]

    return obj

def resolve_driver(driver: str | None = None) -> str:
    """Resolve the active database driver name."""
    if driver:
        return driver.strip().lower()

    cfg_driver = Config("database").get("driver")
    if cfg_driver:
        return str(cfg_driver).strip().lower()

    uri = str(Config("database").get("uri", ""))
    if uri.startswith("mongodb"):
        return "mongodb"

    if Config("database").get("database") and not uri:
        return "sqlite"

    return "mongodb"

def get_database(connection: str = "primary") -> Database:
    """Build a Database instance for the resolved driver."""
    driver = resolve_driver()
    config = Config("database")
    factory = get_adapter(driver)
    adapter = factory()
    adapter.config = config
    return Database(adapter)

async def get_tables() -> list[str]:
    """Return names of all tables in the database."""
    db = get_database()
    return await db.tables()

async def delete_all_records(table_name: str) -> None:
    """Delete all records from a single table."""
    db = get_database()
    source = type(table_name, (), {"table": table_name})
    await db.connect("primary")
    try:
        await db.repository(source).delete_many()
    finally:
        await db.disconnect("primary")

async def backup_table_paginated(table_name: str, path: str, per_page: int = 100) -> int:
    """Back up one table and return its record count."""
    db = get_database()
    counts = await db.backup(path=path, tables=[table_name], page_size=per_page)
    return counts.get(table_name, 0)

async def restore_table_paginated(table_name: str, file_path: str, chunk_size: int = 100) -> int:
    """Restore one table from a backup file and return its record count."""
    if not os.path.exists(file_path):
        Terminal.red.print(f"Backup file '{file_path}' does not exist.")
        return 0

    db = get_database()
    path_dir = os.path.dirname(file_path)
    counts = await db.restore(path=path_dir, tables=[table_name], chunk_size=chunk_size)
    return counts.get(table_name, 0)

async def async_drop(tables: list[str] | None = None) -> None:
    """Delete all records from the target tables."""
    target_tables = tables or await get_tables()
    for table in target_tables:
        await delete_all_records(table)

async def async_backup(
    path: str = "./db", tables: list[str] | None = None, per_page: int = 100
) -> None:
    """Back up the target tables into JSON files."""
    db = get_database()
    await db.backup(path=path, tables=tables, page_size=per_page)

async def async_restore(
    path: str = "./db", tables: list[str] | None = None, chunk_size: int = 100
) -> None:
    """Restore the target tables from JSON backup files."""
    if not os.path.exists(path):
        Terminal.red.print(f"Directory '{path}' does not exist.")
        return
    db = get_database()
    await db.restore(path=path, tables=tables, chunk_size=chunk_size)

def migrate_help() -> None:
    """Print migration subcommand usage."""
    Terminal.cyan.print(
        "Database migration subcommands:\n"
        "  create <name>        Scaffold a new migration file\n"
        "  upgrade              Apply all pending migrations\n"
        "  downgrade            Revert migrations\n"
        "  status               Show applied / pending migration status\n"
        "  check                Verify applied migrations match their files\n"
        "  reset                Revert all migrations\n"
        "  Options: --migrations <dir>, --connection <name>,\n"
        "           --to <version>, --steps <n>, --fake"
    )

async def async_migrate(args: list[str]) -> int:
    """Run a migration subcommand and return the exit code."""
    if not args or args[0] in ("--help", "-h", "help"):
        migrate_help()
        return 0

    sub = args[0]

    path = "migrations"
    connection = "primary"
    flag_args = list(args[1:])

    if "--migrations" in flag_args:
        idx = flag_args.index("--migrations")
        if idx + 1 < len(flag_args):
            path = flag_args[idx + 1]
    if "--connection" in flag_args:
        idx = flag_args.index("--connection")
        if idx + 1 < len(flag_args):
            connection = flag_args[idx + 1]

    fake = "--fake" in flag_args
    target = None
    if "--to" in flag_args:
        idx = flag_args.index("--to")
        if idx + 1 < len(flag_args):
            target = flag_args[idx + 1]
    steps = None
    if "--steps" in flag_args:
        idx = flag_args.index("--steps")
        if idx + 1 < len(flag_args):
            steps = flag_args[idx + 1]

    db = get_database(connection)
    manager = db.migration_manager(path=path, connection=connection)

    if sub == "create":
        name_parts = [a for a in flag_args if not a.startswith("--")]
        if not name_parts:
            Terminal.red.print("migrate create requires a <name> argument.")
            return 1
        file_path = manager.create(name_parts[0])
        Terminal.green.print(f"Created migration: {file_path}")
        return 0

    if sub == "upgrade":
        applied = await manager.upgrade(target=target, fake=fake)
        if applied:
            for version in applied:
                Terminal.green.print(f"Applied {version}")
        else:
            Terminal.cyan.print("No pending migrations.")
        return 0

    if sub == "downgrade":
        try:
            downgrade_target: str | int | None = target
            if steps is not None:
                downgrade_target = int(steps)
            if target is None and steps is None:
                downgrade_target = None
            reverted = await manager.downgrade(target=downgrade_target, fake=fake)
            if reverted:
                for version in reverted:
                    Terminal.green.print(f"Reverted {version}")
            else:
                Terminal.cyan.print("Nothing to downgrade.")
            return 0
        except ValueError:
            Terminal.red.print(
                "Invalid --steps; must be an integer. Use --to <version> for a target version."
            )
            return 1

    if sub == "status":
        statuses = await manager.status()
        if not statuses:
            Terminal.cyan.print("No migrations found.")
            return 0
        for s in statuses:
            mark = "applied" if s.applied else "pending"
            when = f" ({s.applied_at})" if s.applied_at else ""
            Terminal.cyan.print(f"{s.version}  {s.name}  [{mark}]{when}")
        return 0

    if sub == "check":
        try:
            await manager.check()
            Terminal.green.print("All applied migrations are consistent.")
            return 0
        except Exception as exc:
            Terminal.red.print(f"Migration check failed: {exc}")
            return 1

    if sub == "reset":
        reverted = await manager.reset()
        for version in reverted:
            Terminal.green.print(f"Reverted {version}")
        if not reverted:
            Terminal.cyan.print("Nothing to reset.")
        return 0

    Terminal.red.print(f"Unrecognized migrate subcommand: {sub}")
    migrate_help()
    return 1

def drop(tables: list[str] | None = None) -> None:
    """Delete all records from the target tables."""
    asyncio.run(async_drop(tables=tables))

def backup(
    path: str = "./db", tables: list[str] | None = None, per_page: int = 100
) -> None:
    """Back up the target tables into JSON files."""
    asyncio.run(async_backup(path=path, tables=tables, per_page=per_page))

def restore(
    path: str = "./db", tables: list[str] | None = None, chunk_size: int = 100
) -> None:
    """Restore the target tables from JSON backup files."""
    asyncio.run(async_restore(path=path, tables=tables, chunk_size=chunk_size))

def migrate(args: list[str] | None = None) -> int:
    """Run a migration subcommand and return the exit code."""
    if args is None:
        migrate_help()
        return 0
    return asyncio.run(async_migrate(args))

def run(args: list[str] | None = None) -> int:
    """Run the db command with the given arguments."""
    if not args:
        Terminal.cyan.print(DESCRIPTION)
        return 0

    if args[0] == "migrate":
        return migrate(args[1:])

    path = "./db"
    if "--path" in args:
        idx = args.index("--path")
        if idx + 1 < len(args):
            path = args[idx + 1]

    tables: list[str] | None = None
    if "--table" in args:
        idx = args.index("--table")
        if idx + 1 < len(args):
            tables = [args[idx + 1]]

    drv = resolve_driver()
    Terminal.cyan.print(f"Database driver: {drv}")

    try:
        if "--drop" in args:
            drop(tables=tables)
        elif "--backup" in args:
            backup(path=path, tables=tables)
        elif "--restore" in args:
            restore(path=path, tables=tables)
        else:
            Terminal.red.print(f"Unrecognized option(s): {' '.join(args)}")
            Terminal.cyan.print(DESCRIPTION)
            return 1

        Terminal.green.print("Database operation finished successfully.")
        return 0
    except Exception as exc:
        Terminal.red.print(f"Database error: {exc}")
        return 1
