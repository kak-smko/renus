from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from renus.db.core.state import IdentityKind
from renus.db.models.db_field import UNSET, DatabaseField
from renus.db.relationships import RelationshipKind

__all__ = [
    "CheckConstraint",
    "Constraint",
    "FieldMetadata",
    "ForeignKeyConstraint",
    "IdentityMetadata",
    "Index",
    "ModelMetadata",
    "RelationshipMetadata",
    "UniqueConstraint",
]

@dataclass(frozen=True, slots=True)
class FieldMetadata:
    """Describe an immutable model field."""

    name: str
    column_name: str
    python_type: Any
    inferred_type: Any
    storage_type: type | str
    nullable: bool
    required: bool
    database: DatabaseField
    validation: Any = None
    primary_key: bool = False
    identity_kind: IdentityKind | None = None
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
    sensitive: bool = False

    @property
    def has_default(self) -> bool:
        """Whether the field has a default value or factory."""
        return self.default is not UNSET or self.default_factory is not None

    def get_default(self) -> Any:
        """Return the resolved default value, or ``None``."""
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not UNSET:
            return self.default
        return None

@dataclass(frozen=True, slots=True)
class IdentityMetadata:
    """Describe a model's primary key identity."""

    fields: tuple[str, ...]
    kind: IdentityKind
    generated: bool = False

    @property
    def is_composite(self) -> bool:
        """Whether the identity spans multiple fields or is composite."""
        return len(self.fields) > 1 or self.kind == IdentityKind.COMPOSITE

@dataclass(frozen=True, slots=True)
class RelationshipMetadata:
    """Describe a model relationship configuration."""

    name: str
    kind: RelationshipKind | str
    target: type
    local_key: str | None = None
    foreign_key: str | None = None
    through: type | str | None = None
    on_save: str = "no action"
    on_delete: str = "restrict"
    on_update: str = "cascade"
    loading: str = "selectin"
    is_embedded: bool = False
    is_collection: bool = False

    def resolve_target(self) -> type:
        """Return the relationship target model class."""
        if not isinstance(self.target, type):
            raise TypeError(f"Relationship target for '{self.name}' must be a model class")
        return self.target

@dataclass(frozen=True, slots=True)
class Index:
    """Describe a database index on a model."""

    fields: tuple[str, ...]
    unique: bool = False
    name: str | None = None
    type: str | None = None

    def __init__(
        self,
        *fields: str,
        unique: bool = False,
        name: str | None = None,
        type: str | None = None,
    ) -> None:
        """Initialize an index definition.

        Parameters
        ----------
        fields:
            Column field names that make up the index.
        unique:
            Whether the index enforces uniqueness. Defaults to ``False``.
        name:
            Optional index name.
        type:
            Optional index type hint for the target dialect.
        """
        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "unique", unique)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "type", type)

@dataclass(frozen=True, slots=True)
class Constraint:
    """Base class for model constraints."""

    name: str | None = None

@dataclass(frozen=True, slots=True)
class UniqueConstraint(Constraint):
    """A uniqueness constraint over one or more fields."""

    fields: tuple[str, ...] = ()

    def __init__(self, *fields: str, name: str | None = None) -> None:
        """Initialize a unique constraint.

        Parameters
        ----------
        fields:
            Column field names constrained to be unique.
        name:
            Optional constraint name.
        """
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "fields", tuple(fields))

@dataclass(frozen=True, slots=True)
class CheckConstraint(Constraint):
    """A check constraint with a SQL expression."""

    expression: str = ""

    def __init__(self, expression: str, name: str | None = None) -> None:
        """Initialize a check constraint.

        Parameters
        ----------
        expression:
            SQL check expression the constraint enforces.
        name:
            Optional constraint name.
        """
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "name", name)

@dataclass(frozen=True, slots=True)
class ForeignKeyConstraint(Constraint):
    """A foreign key constraint referencing another table."""

    fields: tuple[str, ...] = ()
    reference_table: str = ""
    reference_fields: tuple[str, ...] = ()
    on_delete: str = "RESTRICT"
    on_update: str = "CASCADE"

    def __init__(
        self,
        fields: tuple[str, ...],
        reference_table: str,
        reference_fields: tuple[str, ...],
        on_delete: str = "RESTRICT",
        on_update: str = "CASCADE",
        name: str | None = None,
    ) -> None:
        """Initialize a foreign key constraint.

        Parameters
        ----------
        fields:
            Local column field names in the constraint.
        reference_table:
            Name of the referenced table.
        reference_fields:
            Column names referenced in the target table.
        on_delete:
            Referential action on delete. Defaults to ``"RESTRICT"``.
        on_update:
            Referential action on update. Defaults to ``"CASCADE"``.
        name:
            Optional constraint name.
        """
        object.__setattr__(self, "fields", tuple(fields))
        object.__setattr__(self, "reference_table", reference_table)
        object.__setattr__(self, "reference_fields", tuple(reference_fields))
        object.__setattr__(self, "on_delete", on_delete)
        object.__setattr__(self, "on_update", on_update)
        object.__setattr__(self, "name", name)

@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Hold resolved metadata for a single model."""

    model: type
    table: str
    fields: dict[str, FieldMetadata]
    column_to_field: dict[str, str]
    identity: IdentityMetadata
    relationships: dict[str, RelationshipMetadata] = field(default_factory=dict)
    indexes: tuple[Index, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    timestamps: bool = False
    soft_delete: bool = False
    created_at_field: str | None = None
    updated_at_field: str | None = None
    deleted_at_field: str | None = None
    is_deleted_field: str | None = None

    def get_field(self, name_or_column: str) -> FieldMetadata | None:
        """Look up a field by its attribute or column name."""
        if name_or_column in self.fields:
            return self.fields[name_or_column]
        attr = self.column_to_field.get(name_or_column)
        if attr and attr in self.fields:
            return self.fields[attr]
        return None

    def is_primary_key(self, field_name: str) -> bool:
        """Return whether the named field is part of the primary key."""
        return field_name in self.identity.fields

    @property
    def primary_key_fields(self) -> tuple[str, ...]:
        """Return the field names that form the primary key."""
        return self.identity.fields

    @property
    def primary_key_field(self) -> str:
        """Return the single primary key field name, or raise."""
        if self.identity.is_composite:
            raise ValueError(f"Model '{self.model.__name__}' has a composite primary key: {self.identity.fields}")
        if not self.identity.fields:
            raise ValueError(f"Model '{self.model.__name__}' has no primary key defined")
        return self.identity.fields[0]
