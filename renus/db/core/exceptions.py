from __future__ import annotations

from typing import Any

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
        errors: dict[str, list[Any]] | None = None,
    ) -> None:
        """Construct a validation error from a message or field errors.

        Parameters
        ----------
        message:
            Error message, or a mapping of field to errors / list of errors.
        errors:
            Optional precomputed field-to-errors mapping used for the message.
        """
        self.errors: dict[str, list[Any]] = {}

        if errors is not None:
            self.errors = errors
            msg = self._format_errors(self.errors)
        elif isinstance(message, dict):
            for k, v in message.items():
                self.errors[k] = list(v) if isinstance(v, list) else [v]
            msg = self._format_errors(self.errors)
        elif isinstance(message, list):
            self.errors["__all__"] = list(message)
            msg = self._format_errors(self.errors)
        else:
            msg = str(message)
            self.errors = {"__all__": [msg]}

        super().__init__(msg)
        self.message = msg

    @staticmethod
    def _format_error(field: str, error: Any) -> str:
        if error == "required_error":
            return f"'{field}' is required"
        if error == "internal_error":
            return "Internal validation error"
        if not isinstance(error, (list, tuple)) or not error:
            return str(error)

        code = error[0]
        args = error[1] if len(error) > 1 and isinstance(error[1], (list, tuple)) else []
        if code == "type_error":
            expected = args[0] if args else "correct type"
            return f"'{field}' must be of type {expected}"
        if code == "unknown_field":
            name = args[0] if args else field
            return f"Unknown field '{name}'"
        if code == "min_error":
            return f"'{field}' must be greater than or equal to {args[0]}"
        if code == "max_error":
            return f"'{field}' must be less than or equal to {args[0]}"
        if code == "eq_error":
            return f"'{field}' must be equal to {args[0]}"
        if code == "min_len_error":
            return f"'{field}' length must be at least {args[0]}"
        if code == "max_len_error":
            return f"'{field}' length must be at most {args[0]}"
        if code == "len_error":
            return f"'{field}' length must be {args[0]}"
        return str(error)

    @classmethod
    def _format_errors(cls, errors: dict[str, Any]) -> str:
        lines = ["Validation failed:"]
        for field, err_list in errors.items():
            if isinstance(err_list, (list, tuple)):
                err_text = "; ".join(cls._format_error(field, error) for error in err_list)
            else:
                err_text = cls._format_error(field, err_list)
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
