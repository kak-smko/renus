from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from renus.db.core.exceptions import UnsupportedOperationError
from renus.db.core.portability import Portability, PortabilityKind

__all__ = ["DatabaseCapabilities", "require_capability"]

@dataclass(frozen=True, slots=True)
class DatabaseCapabilities:
    """Immutable set of supported database capabilities."""

    transactions: bool = False

    nested_documents: bool = False

    joins: bool = False

    foreign_keys: bool = False

    upsert: bool = False

    returning: bool = False

    json: bool = False

    arrays: bool = False

    cursor_pagination: bool = False

    bulk_operations: bool = False

    indexes: bool = False

    constraints: bool = False

    _NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "transactions",
            "nested_documents",
            "joins",
            "foreign_keys",
            "upsert",
            "returning",
            "json",
            "arrays",
            "cursor_pagination",
            "bulk_operations",
            "indexes",
            "constraints",
        }
    )

    _PORTABILITY: ClassVar[dict[str, PortabilityKind]] = {name: PortabilityKind.CAPABILITY_DEPENDENT for name in _NAMES}

    @classmethod
    def names(cls) -> frozenset[str]:
        """Return all known capability names."""
        return cls._NAMES

    @classmethod
    def none(cls) -> DatabaseCapabilities:
        """Return a capabilities set with no features enabled."""
        return cls()

    def supports(self, name: str) -> bool:
        """Return whether the named capability is supported."""
        if name not in self._NAMES:
            raise UnsupportedOperationError(f"unknown capability {name!r}")
        return bool(getattr(self, name, False))

    def require(self, name: str) -> None:
        """Raise if the named capability is not supported."""
        if not self.supports(name):
            raise UnsupportedOperationError(
                f"operation requires capability {name!r}, which the adapter does not support"
            )

    def portability(self, name: str) -> Portability:
        """Return the portability of the named capability."""
        kind = self._PORTABILITY.get(name)
        if kind is None:
            raise UnsupportedOperationError(f"unknown capability {name!r}")
        return Portability(kind)

CAPABILITIES: Final = DatabaseCapabilities._NAMES

def require_capability(capabilities: DatabaseCapabilities, name: str) -> None:
    """Require the named capability or raise an error."""
    capabilities.require(name)
