from __future__ import annotations

from typing import Any

__all__ = [
    "ConfigurationError",
    "ConnectionError",
    "DatabaseError",
    "DuplicateKeyError",
    "IntegrityError",
    "MutationError",
    "NotFoundError",
    "QueryError",
    "TransactionError",
    "DBError",
    "UnsupportedOperationError",
    "ValidationError",
]

class DBError(Exception):
    """Base class for all database errors."""
    pass

class DatabaseError(DBError):
    """Base class for database operation errors."""
    pass

class ConfigurationError(DBError):
    """Raised when database configuration is invalid."""
    pass

class ConnectionError(DBError):
    """Raised when a database connection cannot be established."""
    pass

class QueryError(DatabaseError):
    """Raised when a query fails to execute."""
    pass

class MutationError(DatabaseError):
    """Raised when a mutation fails to execute."""
    pass

class ValidationError(DBError, ValueError):
    """Raised when data fails validation."""

    def __init__(
        self,
        message: str | dict[str, Any] | list[Any],
        errors: dict[str, list[str]] | None = None,
    ) -> None:
        """Construct a validation error from a message or field errors.

        Parameters
        ----------
        message:
            Error message, or a mapping of field to errors / list of errors.
        errors:
            Optional precomputed field-to-errors mapping used for the message.
        """
        self.errors: dict[str, list[str]] = {}

        if errors is not None:
            self.errors = errors
            msg = self._format_errors(self.errors)
        elif isinstance(message, dict):
            for k, v in message.items():
                if isinstance(v, list):
                    self.errors[k] = [str(x) for x in v]
                else:
                    self.errors[k] = [str(v)]
            msg = self._format_errors(self.errors)
        elif isinstance(message, list):
            self.errors["__all__"] = [str(x) for x in message]
            msg = self._format_errors(self.errors)
        else:
            msg = str(message)
            self.errors = {"__all__": [msg]}

        super().__init__(msg)
        self.message = msg

    @staticmethod
    def _format_errors(errors: dict[str, Any]) -> str:
        lines = ["Validation failed:"]
        for field, err_list in errors.items():
            if isinstance(err_list, (list, tuple)):
                err_text = "; ".join(str(e) for e in err_list)
            else:
                err_text = str(err_list)
            lines.append(f"  {field}: {err_text}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"ValidationError({self.errors})"

class NotFoundError(DatabaseError):
    """Raised when a requested record is not found."""
    pass

class IntegrityError(DatabaseError):
    """Raised on a database integrity violation."""
    pass

class DuplicateKeyError(IntegrityError):
    """Raised when a unique key constraint is violated."""
    pass

class TransactionError(DatabaseError):
    """Raised when a transaction fails."""
    pass

class UnsupportedOperationError(DBError):
    """Raised when an operation is not supported by the backend."""
    pass
