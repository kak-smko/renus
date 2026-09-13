from __future__ import annotations

from renus.db.core.exceptions import DBError

__all__ = [
    "MigrationChecksumError",
    "MigrationError",
    "MigrationNotFoundError",
]

class MigrationError(DBError):
    """Base exception for migration failures."""

    pass

class MigrationChecksumError(MigrationError):
    """Raised when a migration's checksum does not match."""

    pass

class MigrationNotFoundError(MigrationError):
    """Raised when a migration file cannot be located."""

    pass
