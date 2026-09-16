from __future__ import annotations

import binascii
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from renus.db.core.state import IdentityKind

__all__ = ["UNSET", "DatabaseField"]

_UNSET_SENTINEL = object()
UNSET = _UNSET_SENTINEL

@dataclass(frozen=True, slots=True)
class DatabaseField:
    """Immutable metadata describing a field's column and storage options."""

    column_name: str | None = None
    storage_type: type | str | None = None
    nullable: bool | None = None
    primary_key: bool = False
    auto_inc: bool = False
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
