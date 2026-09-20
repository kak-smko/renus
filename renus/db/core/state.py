from __future__ import annotations

from enum import Enum


class Lifecycle(str, Enum):
    """Lifecycle states of an entity."""

    NEW = "new"
    PERSISTED = "persisted"
    DIRTY = "dirty"
    DELETED = "deleted"
    DETACHED = "detached"

class IdentityKind(str, Enum):
    """Kinds of identity generated for entities."""

    INTEGER = "integer"
    UUID = "uuid"
    STRING = "string"
    COMPOSITE = "composite"
    GENERATED = "generated"
    ID = "id"
