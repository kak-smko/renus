from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Any

__all__ = [
    "Embedded",
    "EmbeddedMany",
    "EmbeddedOne",
    "ManyToMany",
    "ManyToOne",
    "OneToMany",
    "OneToOne",
    "Reference",
    "Relationship",
    "RelationshipKind",
]

class RelationshipKind(str, Enum):
    """Values describing the cardinality of a relationship."""

    EMBEDDED_ONE = "embedded_one"
    EMBEDDED_MANY = "embedded_many"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    REFERENCE = "reference"

class Relationship:
    """Descriptor defining a relationship between models."""

    def __init__(
        self,
        kind: RelationshipKind | str,
        target: type | str,
        cascade: Iterable[str] = (),
        on_delete: str = "restrict",
        on_update: str = "cascade",
        loading: str = "selectin",
        local_key: str | None = None,
        foreign_key: str | None = None,
        through: type | str | None = None,
        is_embedded: bool = False,
        is_collection: bool = False,
    ) -> None:
        """Configure a relationship descriptor.

        Parameters
        ----------
        kind:
            The cardinality of the relationship.
        target:
            The related model class or a reference to it.
        cascade:
            Operations to cascade to related records. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to none.
        on_delete:
            Action taken when the related record is deleted. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"restrict"``.
        on_update:
            Action taken when the related record is updated. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"cascade"``.
        loading:
            Strategy used to load the related records. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        local_key:
            The local column used to join the relationship. Defaults to the
            owner's primary key.
        foreign_key:
            The column on the target used to join the relationship. Defaults
            to the target's primary key.
        through:
            The intermediate model used for many-to-many relationships.
        is_embedded:
            Whether the target is stored inline with the owner.
        is_collection:
            Whether the relationship resolves to multiple records.
        """
        self.kind = RelationshipKind(kind) if isinstance(kind, str) else kind
        self.target = target
        self.cascade = frozenset(cascade)
        self.on_delete = on_delete
        self.on_update = on_update
        self.loading = loading
        self.local_key = local_key
        self.foreign_key = foreign_key
        self.through = through
        self.is_embedded = is_embedded
        self.is_collection = is_collection
        self._name: str | None = None
        self._owner: type | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        self._owner = owner
        self._name = name

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:

            from renus.db.query.ast import Path

            model = owner or self._owner or object
            return Path(model, (self._name or "",))

        if self._name is not None and self._name in instance.__dict__:
            return instance.__dict__[self._name]

        return [] if self.is_collection else None

    def __set__(self, instance: Any, value: Any) -> None:
        if self._name is not None:
            instance.__dict__[self._name] = value

class EmbeddedOne(Relationship):

    def __init__(
        self,
        target: type | str,
        *,
        cascade: Iterable[str] = ("all",),
        loading: str = "selectin",
    ) -> None:
        """Declare an embedded single relationship.

        Parameters
        ----------
        target:
            The embedded model class or a reference to it.
        cascade:
            Operations cascaded to the embedded record. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to ``"all"``.
        loading:
            Strategy used to load the embedded record. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            kind=RelationshipKind.EMBEDDED_ONE,
            target=target,
            cascade=cascade,
            on_delete="cascade",
            on_update="cascade",
            loading=loading,
            is_embedded=True,
            is_collection=False,
        )

Embedded = EmbeddedOne

class EmbeddedMany(Relationship):

    def __init__(
        self,
        target: type | str,
        *,
        cascade: Iterable[str] = ("all",),
        loading: str = "selectin",
    ) -> None:
        """Declare an embedded collection relationship.

        Parameters
        ----------
        target:
            The embedded model class or a reference to it.
        cascade:
            Operations cascaded to the embedded records. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to ``"all"``.
        loading:
            Strategy used to load the embedded records. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            kind=RelationshipKind.EMBEDDED_MANY,
            target=target,
            cascade=cascade,
            on_delete="cascade",
            on_update="cascade",
            loading=loading,
            is_embedded=True,
            is_collection=True,
        )

class Reference(Relationship):

    def __init__(
        self,
        target: type | str,
        *,
        local_key: str | None = None,
        foreign_key: str | None = None,
        cascade: Iterable[str] = (),
        on_delete: str = "restrict",
        on_update: str = "cascade",
        loading: str = "selectin",
        kind: RelationshipKind | str = RelationshipKind.REFERENCE,
        is_collection: bool = False,
    ) -> None:
        """Declare a reference relationship.

        Parameters
        ----------
        target:
            The referenced model class or a reference to it.
        local_key:
            The local column used to join. Defaults to the owner's primary key.
        foreign_key:
            The column on the target used to join. Defaults to the target's
            primary key.
        cascade:
            Operations to cascade to related records. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to none.
        on_delete:
            Action taken when the related record is deleted. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"restrict"``.
        on_update:
            Action taken when the related record is updated. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"cascade"``.
        loading:
            Strategy used to load the related records. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        kind:
            The cardinality of the relationship. Defaults to ``"reference"``.
        is_collection:
            Whether the relationship resolves to multiple records.
        """
        super().__init__(
            kind=kind,
            target=target,
            cascade=cascade,
            on_delete=on_delete,
            on_update=on_update,
            loading=loading,
            local_key=local_key,
            foreign_key=foreign_key,
            is_embedded=False,
            is_collection=is_collection,
        )

class OneToOne(Reference):

    def __init__(
        self,
        target: type | str,
        *,
        local_key: str | None = None,
        foreign_key: str | None = None,
        cascade: Iterable[str] = (),
        on_delete: str = "restrict",
        on_update: str = "cascade",
        loading: str = "selectin",
    ) -> None:
        """Declare a one-to-one relationship.

        Parameters
        ----------
        target:
            The related model class or a reference to it.
        local_key:
            The local column used to join. Defaults to the owner's primary key.
        foreign_key:
            The column on the target used to join. Defaults to the target's
            primary key.
        cascade:
            Operations to cascade to related records. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to none.
        on_delete:
            Action taken when the related record is deleted. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"restrict"``.
        on_update:
            Action taken when the related record is updated. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"cascade"``.
        loading:
            Strategy used to load the related record. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            target=target,
            local_key=local_key,
            foreign_key=foreign_key,
            cascade=cascade,
            on_delete=on_delete,
            on_update=on_update,
            loading=loading,
            kind=RelationshipKind.ONE_TO_ONE,
            is_collection=False,
        )

class OneToMany(Reference):

    def __init__(
        self,
        target: type | str,
        *,
        local_key: str | None = None,
        foreign_key: str | None = None,
        cascade: Iterable[str] = (),
        on_delete: str = "restrict",
        on_update: str = "cascade",
        loading: str = "selectin",
    ) -> None:
        """Declare a one-to-many relationship.

        Parameters
        ----------
        target:
            The related model class or a reference to it.
        local_key:
            The local column used to join. Defaults to the owner's primary key.
        foreign_key:
            The column on the target used to join. Defaults to the target's
            primary key.
        cascade:
            Operations to cascade to related records. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to none.
        on_delete:
            Action taken when the related record is deleted. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"restrict"``.
        on_update:
            Action taken when the related record is updated. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"cascade"``.
        loading:
            Strategy used to load the related records. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            target=target,
            local_key=local_key,
            foreign_key=foreign_key,
            cascade=cascade,
            on_delete=on_delete,
            on_update=on_update,
            loading=loading,
            kind=RelationshipKind.ONE_TO_MANY,
            is_collection=True,
        )

class ManyToOne(Reference):

    def __init__(
        self,
        target: type | str,
        *,
        local_key: str | None = None,
        foreign_key: str | None = None,
        cascade: Iterable[str] = (),
        on_delete: str = "restrict",
        on_update: str = "cascade",
        loading: str = "selectin",
    ) -> None:
        """Declare a many-to-one relationship.

        Parameters
        ----------
        target:
            The related model class or a reference to it.
        local_key:
            The local column used to join. Defaults to the owner's primary key.
        foreign_key:
            The column on the target used to join. Defaults to the target's
            primary key.
        cascade:
            Operations to cascade to related records. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to none.
        on_delete:
            Action taken when the related record is deleted. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"restrict"``.
        on_update:
            Action taken when the related record is updated. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"cascade"``.
        loading:
            Strategy used to load the related record. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            target=target,
            local_key=local_key,
            foreign_key=foreign_key,
            cascade=cascade,
            on_delete=on_delete,
            on_update=on_update,
            loading=loading,
            kind=RelationshipKind.MANY_TO_ONE,
            is_collection=False,
        )

class ManyToMany(Reference):

    def __init__(
        self,
        target: type | str,
        *,
        through: type | str | None = None,
        local_key: str | None = None,
        foreign_key: str | None = None,
        cascade: Iterable[str] = (),
        on_delete: str = "restrict",
        on_update: str = "cascade",
        loading: str = "selectin",
    ) -> None:
        """Declare a many-to-many relationship.

        Parameters
        ----------
        target:
            The related model class or a reference to it.
        through:
            The intermediate join model.
        local_key:
            The local column used to join. Defaults to the owner's primary key.
        foreign_key:
            The column on the target used to join. Defaults to the target's
            primary key.
        cascade:
            Operations to cascade to related records. Valid values are
            ``"all"``, ``"save"``, and ``"delete"``. Defaults to none.
        on_delete:
            Action taken when the related record is deleted. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"restrict"``.
        on_update:
            Action taken when the related record is updated. One of
            ``"cascade"``, ``"restrict"``, ``"set null"``, ``"set default"``,
            or ``"no action"``. Defaults to ``"cascade"``.
        loading:
            Strategy used to load the related records. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            target=target,
            local_key=local_key,
            foreign_key=foreign_key,
            cascade=cascade,
            on_delete=on_delete,
            on_update=on_update,
            loading=loading,
            kind=RelationshipKind.MANY_TO_MANY,
            is_collection=True,
        )
        self.through = through
