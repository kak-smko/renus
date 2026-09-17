from __future__ import annotations

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
    primary_key: bool = False
    auto_inc: bool = False
    identity_kind: "IdentityKind | str | None" = None
    generated: bool = False
    unique: bool = False
    indexed: bool = False
    index_name: str | None = None
    foreign_key: str | None = None
    on_delete: str | None = None
    on_update: str | None = None
    immutable: bool = False
    comment: str | None = None
