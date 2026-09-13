from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from renus.db.database import Database
from renus.db.migrations.context import MigrationContext
from renus.db.migrations.exceptions import (
    MigrationChecksumError,
    MigrationError,
    MigrationNotFoundError,
)
from renus.db.migrations.tracker import MigrationRecord, MigrationTracker

__all__ = [
    "MigrationManager",
    "MigrationRecord",
    "MigrationStatus",
]

@dataclass(frozen=True)
class MigrationStatus:
    """Describe the applied status of a single migration."""

    version: str
    name: str
    applied: bool
    applied_at: str | None
    checksum: str
    file_path: Path

class MigrationManager:
    """Discover, apply, and track database migrations."""

    def __init__(
        self,
        db: Database,
        path: str | Path = "migrations",
        connection: str = "primary",
    ) -> None:
        """Bind the manager to a database and migration directory.

        Parameters
        ----------
        db:
            The database migrations run against.
        path:
            Directory containing migration files. Defaults to ``"migrations"``.
        connection:
            Connection name to use. Defaults to ``"primary"``.
        """
        self.db = db
        self.path = Path(path)
        self.connection = connection
        self.adapter = db.adapter(connection)
        self.tracker = MigrationTracker(self.adapter)

    def _calculate_checksum(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _discover_migration_files(self) -> list[tuple[str, str, Path]]:
        if not self.path.exists():
            return []

        files: list[tuple[str, str, Path]] = []
        for p in sorted(self.path.glob("*.py")):
            if p.name.startswith("__") or p.name.startswith("."):
                continue
            stem = p.stem
            version = stem
            if "_" in stem:
                _, name = stem.split("_", 1)
            else:
                name = stem
            files.append((version, name, p))

        return files

    def create(self, name: str) -> Path:
        """Scaffold a new migration file and return its path."""
        self.path.mkdir(parents=True, exist_ok=True)
        existing = self._discover_migration_files()
        next_num = len(existing) + 1
        clean_name = "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()
        filename = f"{next_num:04d}_{clean_name}.py"
        file_path = self.path / filename

        template = (
            f'"""Migration: {clean_name}"""\n\n'
            "from renus.db.migrations import Column, MigrationContext\n\n\n"
            "async def upgrade(ctx: MigrationContext) -> None:\n"
            "    pass\n\n\n"
            "async def downgrade(ctx: MigrationContext) -> None:\n"
            "    pass\n"
        )
        file_path.write_text(template, encoding="utf-8")
        return file_path

    async def _load_and_run(
        self,
        file_path: Path,
        func_name: str,
        ctx: MigrationContext,
    ) -> None:
        code = file_path.read_text(encoding="utf-8")
        ns: dict[str, Any] = {}
        try:
            compiled = compile(code, str(file_path), "exec")
            exec(compiled, ns)
        except Exception as e:
            raise MigrationError(f"Failed to load migration file '{file_path.name}': {e}") from e

        fn = ns.get(func_name)
        if fn is None:
            raise MigrationError(f"Migration '{file_path.name}' does not define '{func_name}'")

        sig = inspect.signature(fn)
        if len(sig.parameters) >= 1:
            res = fn(ctx)
        else:
            res = fn()

        if inspect.isawaitable(res):
            await res

    async def upgrade(
        self,
        target: str | None = None,
        fake: bool = False,
    ) -> list[str]:
        """Apply pending migrations up to the optional target version."""
        self.path.mkdir(parents=True, exist_ok=True)
        files = self._discover_migration_files()
        applied = await self.tracker.get_applied_migrations()
        applied_map = {r.version: r for r in applied}

        file_map = {v: (n, p) for v, n, p in files}
        for v, r in applied_map.items():
            if v in file_map:
                _, p = file_map[v]
                actual_checksum = self._calculate_checksum(p.read_text(encoding="utf-8"))
                if actual_checksum != r.checksum:
                    raise MigrationChecksumError(
                        f"Checksum mismatch for applied migration '{v}'. "
                        f"Expected {r.checksum}, got {actual_checksum}."
                    )

        applied_versions: list[str] = []
        ctx = MigrationContext(self.db, adapter=self.adapter, connection=self.connection)

        for version, name, file_path in files:
            if version in applied_map:
                continue

            content = file_path.read_text(encoding="utf-8")
            checksum = self._calculate_checksum(content)

            supports_tx = self.adapter.capabilities.supports("transactions")
            if not fake:
                if supports_tx:
                    async with self.db.transaction(self.connection):
                        await self._load_and_run(file_path, "upgrade", ctx)
                        await self.tracker.record_migration(version, name, checksum)
                else:
                    await self._load_and_run(file_path, "upgrade", ctx)
                    await self.tracker.record_migration(version, name, checksum)
            else:
                await self.tracker.record_migration(version, name, checksum)

            applied_versions.append(version)

            if target is not None and (target == version or version.startswith(target)):
                break

        return applied_versions

    async def downgrade(
        self,
        target: str | int | None = None,
        fake: bool = False,
    ) -> list[str]:
        """Revert applied migrations down to the optional target."""
        applied = await self.tracker.get_applied_migrations()
        if not applied:
            return []

        files = self._discover_migration_files()
        file_map = {v: (n, p) for v, n, p in files}

        to_revert: list[MigrationRecord] = []
        reversed_applied = list(reversed(applied))

        if target is None:

            to_revert = [reversed_applied[0]]
        elif isinstance(target, int):

            to_revert = reversed_applied[:max(0, target)]
        elif isinstance(target, str):
            if target in ("0", "base"):
                to_revert = reversed_applied
            else:

                for r in reversed_applied:
                    if r.version == target or r.version.startswith(target):
                        break
                    to_revert.append(r)

        reverted_versions: list[str] = []
        ctx = MigrationContext(self.db, adapter=self.adapter, connection=self.connection)

        for rec in to_revert:
            if rec.version not in file_map:
                raise MigrationNotFoundError(
                    f"Migration file for applied version '{rec.version}' not found on disk"
                )

            _, file_path = file_map[rec.version]
            supports_tx = self.adapter.capabilities.supports("transactions")

            if not fake:
                if supports_tx:
                    async with self.db.transaction(self.connection):
                        await self._load_and_run(file_path, "downgrade", ctx)
                        await self.tracker.remove_migration(rec.version)
                else:
                    await self._load_and_run(file_path, "downgrade", ctx)
                    await self.tracker.remove_migration(rec.version)
            else:
                await self.tracker.remove_migration(rec.version)

            reverted_versions.append(rec.version)

        return reverted_versions

    async def status(self) -> list[MigrationStatus]:
        """Return the status of every discovered migration."""
        files = self._discover_migration_files()
        applied = await self.tracker.get_applied_migrations()
        applied_map = {r.version: r for r in applied}

        statuses: list[MigrationStatus] = []
        for version, name, file_path in files:
            content = file_path.read_text(encoding="utf-8")
            checksum = self._calculate_checksum(content)
            rec = applied_map.get(version)
            statuses.append(
                MigrationStatus(
                    version=version,
                    name=name,
                    applied=rec is not None,
                    applied_at=rec.applied_at if rec else None,
                    checksum=checksum,
                    file_path=file_path,
                )
            )
        return statuses

    async def reset(self) -> list[str]:
        """Revert all applied migrations."""
        return await self.downgrade(target="base")

    async def check(self) -> bool:
        """Verify applied migrations match their files on disk."""
        statuses = await self.status()
        applied = await self.tracker.get_applied_migrations()
        applied_map = {r.version: r for r in applied}

        for s in statuses:
            if s.version in applied_map:
                rec = applied_map[s.version]
                if rec.checksum != s.checksum:
                    raise MigrationChecksumError(
                        f"Checksum mismatch on applied migration '{s.version}'. "
                        f"Database has {rec.checksum}, disk has {s.checksum}."
                    )
        return True
