from __future__ import annotations

from renus.db.core.exceptions import (
    ConfigurationError,
    ConnectionError as DBConnectionError,
    DatabaseError,
    DuplicateKeyError,
    IntegrityError,
    MutationError,
    NotFoundError,
    QueryError,
    TransactionError,
    DBError,
    UnsupportedOperationError,
    ValidationError,
)

ConnectionError = DBConnectionError

_CONNECTION_TYPE_MARKERS = (
    "Connection",
    "OperationalError",
    "AutoReconnect",
    "ConnectionFailure",
    "NetworkTimeout",
    "ServerSelection",
    "NotMaster",
    "BrokenPipe",
    "ConnectionReset",
    "ConnectionRefused",
    "ClosedResource",
    "TimeoutError",
)

_CONNECTION_MSG_MARKERS = (
    "gone away",
    "lost connection",
    "connection lost",
    "server has gone away",
    "connection is closed",
    "cannot operate on a closed database",
    "connection refused",
    "failed to connect",
    "network timeout",
    "not master",
)

def is_connection_error(exc: BaseException) -> bool:
    """Return True if an exception indicates a connection failure."""
    name = type(exc).__name__.lower()
    for marker in _CONNECTION_TYPE_MARKERS:
        if marker.lower() in name:
            return True
    message = str(exc).lower()
    for marker in _CONNECTION_MSG_MARKERS:
        if marker in message:
            return True
    return False

def translate_driver_error(
    label: str,
    backend: str,
    exc: BaseException,
    operation: str,
) -> DBError:
    """Map a driver exception to a domain-specific ``DBError``."""
    message = str(exc)
    name = type(exc).__name__

    if is_connection_error(exc):
        return DBConnectionError(f"{label} connection error: {message}")

    if backend == "sqlite":
        if name == "IntegrityError":
            if "UNIQUE" in message or "PRIMARY" in message:
                return DuplicateKeyError(f"SQLite integrity error: {message}")
            return IntegrityError(f"SQLite integrity error: {message}")
    elif backend == "mysql":
        if "1062" in message or "Duplicate entry" in message:
            return DuplicateKeyError(f"MySQL duplicate key error: {message}")
        if "IntegrityError" in name or "foreign key" in message.lower():
            return IntegrityError(f"MySQL integrity error: {message}")
    elif backend == "mongodb":
        if "E11000" in message or "DuplicateKey" in name:
            return DuplicateKeyError(f"MongoDB duplicate key error: {message}")

    return DatabaseError(f"{label} {operation} error: {message}")
