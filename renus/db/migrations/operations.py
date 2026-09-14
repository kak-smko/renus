from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Column",
    "TableDefinition",
]

@dataclass
class Column:
    """Describe a single column for schema DDL."""

    name: str
    type: str | type = "str"
    nullable: bool = True
    primary_key: bool = False
    generated: bool = False
    unique: bool = False
    default: Any = None
    foreign_key: str | None = None
    on_delete: str | None = None
    on_update: str | None = None
    comment: str | None = None

@dataclass
class TableDefinition:
    """Describe a table and its columns."""

    name: str
    columns: list[Column] = field(default_factory=list)
