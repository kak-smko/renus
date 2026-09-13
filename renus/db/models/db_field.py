from __future__ import annotations

import binascii
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from renus.db.core.state import IdentityKind

__all__ = ["UNSET", "DatabaseField", "ObjectId"]

_UNSET_SENTINEL = object()
UNSET = _UNSET_SENTINEL

class ObjectId(str):
    """A 24-character hexadecimal object identifier stored as a string."""

    __slots__ = ()

    def __new__(cls, oid: str | bytes | None = None) -> ObjectId:
        """Construct an ObjectId from a value or generate a new one.

        Parameters
        ----------
        oid:
            Existing 24-character hex string or bytes. When ``None``, a new
            timestamp and randomness based ObjectId is generated.
        """
        if oid is None:

            timestamp = int(time.time()).to_bytes(4, byteorder="big")
            random_bytes = os.urandom(8)
            oid_str = binascii.hexlify(timestamp + random_bytes).decode("ascii")
        elif isinstance(oid, bytes):
            oid_str = oid.decode("ascii")
        else:
            oid_str = str(oid)

        if len(oid_str) != 24 or not all(c in "0123456789abcdefABCDEF" for c in oid_str):
            raise ValueError(f"'{oid_str}' is not a valid 24-character hexadecimal ObjectId")

        return super().__new__(cls, oid_str.lower())

    def __repr__(self) -> str:
        return f"ObjectId('{self}')"

@dataclass(frozen=True, slots=True)
class DatabaseField:
    """Immutable metadata describing a field's column and storage options."""

    column_name: str | None = None
    storage_type: type | str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    identity_kind: "IdentityKind | str | None" = None
    generated: bool = False
    unique: bool = False
    indexed: bool = False
    index_name: str | None = None
    default: Any = UNSET
    default_factory: Callable[[], Any] | None = None
    foreign_key: str | None = None
    on_delete: str | None = None
    on_update: str | None = None
    immutable: bool = False
    comment: str | None = None

    @property
    def has_default(self) -> bool:
        """Return whether a default value or default factory is defined."""
        return self.default is not UNSET or self.default_factory is not None

    def get_default(self) -> Any:
        """Return the resolved default value, or ``None`` when none is set."""
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not UNSET:
            return self.default
        return None
