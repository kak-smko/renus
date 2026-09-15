from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = [
    "Embedded",
    "EmbeddedMany",
    "EmbeddedOne",
    "LoadingStrategy",
    "ManyToMany",
    "ManyToOne",
    "OneToMany",
    "OneToOne",
    "Reference",
    "ReferentialAction",
    "Relationship",
    "RelationshipKind",
    "SaveAction",
]

class RelationshipKind(str, Enum):

    EMBEDDED_ONE = "embedded_one"
    EMBEDDED_MANY = "embedded_many"
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    REFERENCE = "reference"

class SaveAction(str, Enum):

    CASCADE = "cascade"
    NO_ACTION = "no action"

class ReferentialAction(str, Enum):

    CASCADE = "cascade"
    RESTRICT = "restrict"
    SET_NULL = "set null"
    SET_DEFAULT = "set default"
    NO_ACTION = "no action"

class LoadingStrategy(str, Enum):

    SELECTIN = "selectin"
    JOINED = "joined"

_SAVE_ALIASES: dict[str, SaveAction] = {
    "cascade": SaveAction.CASCADE,
    "save": SaveAction.CASCADE,
    "no action": SaveAction.NO_ACTION,
    "none": SaveAction.NO_ACTION,
}

_REFERENTIAL_ALIASES: dict[str, ReferentialAction] = {
    "cascade": ReferentialAction.CASCADE,
    "restrict": ReferentialAction.RESTRICT,
    "set null": ReferentialAction.SET_NULL,
    "setnull": ReferentialAction.SET_NULL,
    "set default": ReferentialAction.SET_DEFAULT,
    "setdefault": ReferentialAction.SET_DEFAULT,
    "no action": ReferentialAction.NO_ACTION,
    "noaction": ReferentialAction.NO_ACTION,
    "none": ReferentialAction.NO_ACTION,
}

_LOADING_ALIASES: dict[str, LoadingStrategy] = {
    "selectin": LoadingStrategy.SELECTIN,
    "select in": LoadingStrategy.SELECTIN,
    "joined": LoadingStrategy.JOINED,
    "join": LoadingStrategy.JOINED,
}

def _normalize_option(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    text = str(value).strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(text.split())

def _referential_action_choices() -> str:
    return ", ".join(action.value for action in ReferentialAction)

def _resolve_save_action(value: Any) -> str:
    if isinstance(value, SaveAction):
        return value.value
    if value is None:
        return SaveAction.NO_ACTION.value
    action = _SAVE_ALIASES.get(_normalize_option(value))
    if action is None:
        raise ValueError(f"invalid on_save {value!r}; must be one of: cascade, no action")
    return action.value

def _resolve_referential_action(value: Any, option: str) -> str:
    if isinstance(value, ReferentialAction):
        return value.value
    if value is None:
        raise ValueError(f"{option} must be one of: {_referential_action_choices()}")
    action = _REFERENTIAL_ALIASES.get(_normalize_option(value))
    if action is None:
        raise ValueError(
            f"invalid {option} {value!r}; must be one of: {_referential_action_choices()}"
        )
    return action.value

def _resolve_loading(value: Any) -> str:
    if isinstance(value, LoadingStrategy):
        return value.value
    strategy = _LOADING_ALIASES.get(_normalize_option(value))
    if strategy is None:
        raise ValueError(
            f"invalid loading strategy {value!r}; must be one of: selectin, joined"
        )
    return strategy.value

class Relationship:
    """Descriptor defining a relationship between models."""

    def __init__(
        self,
        kind: RelationshipKind | str,
        target: type | str,
        on_save: SaveAction | str = "no action",
        on_delete: str | ReferentialAction = "restrict",
        on_update: str | ReferentialAction = "cascade",
        loading: str | LoadingStrategy = "selectin",
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
        on_save:
            Whether related records are cascaded when the owner is saved. One
            of ``"cascade"`` or ``"no action"``. Defaults to ``"no action"``.
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

        on_delete and on_update options:
        | Action | Behavior When Parent Record is Deleted (or Updated) |
        | :--- | :--- |
        | **CASCADE** | Child records are **automatically deleted** (or updated) along with the parent. |
        | **RESTRICT** | The deletion is **blocked** and the database throws an **Error**. |
        | **SET NULL** | The Foreign Key in the child record is set to **NULL**. |
        | **SET DEFAULT** | The Foreign Key in the child record is set to its **Default** value. |
        | **NO ACTION** | No Action. |

        """
        self.kind = RelationshipKind(kind) if isinstance(kind, str) else kind
        self.target = target
        self.on_save = _resolve_save_action(on_save)
        self.on_delete = _resolve_referential_action(on_delete, "on_delete")
        self.on_update = _resolve_referential_action(on_update, "on_update")
        self.loading = _resolve_loading(loading)
        self.local_key = local_key
        self.foreign_key = foreign_key
        self.through = through
        self.is_embedded = is_embedded
        self.is_collection = is_collection
        self._name: str | None = None
        self._owner: type | None = None

    @property
    def on_save_action(self) -> SaveAction:
        return SaveAction(self.on_save)

    @property
    def cascades_on_save(self) -> bool:
        return self.on_save_action is SaveAction.CASCADE

    @property
    def on_delete_action(self) -> ReferentialAction:
        return ReferentialAction(self.on_delete)

    @property
    def on_update_action(self) -> ReferentialAction:
        return ReferentialAction(self.on_update)

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
        loading: str | LoadingStrategy = "selectin",
    ) -> None:
        """Declare an embedded single relationship.

        Parameters
        ----------
        target:
            The embedded model class or a reference to it.

        loading:
            Strategy used to load the embedded record. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            kind=RelationshipKind.EMBEDDED_ONE,
            target=target,
            on_save="cascade",
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

        loading: str | LoadingStrategy = "selectin",
    ) -> None:
        """Declare an embedded collection relationship.

        Parameters
        ----------
        target:
            The embedded model class or a reference to it.

        loading:
            Strategy used to load the embedded records. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            kind=RelationshipKind.EMBEDDED_MANY,
            target=target,
            on_save="cascade",
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
        on_save: SaveAction | str = "no action",
        on_delete: str | ReferentialAction = "restrict",
        on_update: str | ReferentialAction = "cascade",
        loading: str | LoadingStrategy = "selectin",
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
        on_save:
            Whether related records are cascaded when the owner is saved. One
            of ``"cascade"`` or ``"no action"``. Defaults to ``"no action"``.
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
            on_save=on_save,
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
        on_save: SaveAction | str = "no action",
        on_delete: str | ReferentialAction = "restrict",
        on_update: str | ReferentialAction = "cascade",
        loading: str | LoadingStrategy = "selectin",
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
        on_save:
            Whether the related record is cascaded when the owner is saved. One
            of ``"cascade"`` or ``"no action"``. Defaults to ``"no action"``.
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
            on_save=on_save,
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
        on_save: SaveAction | str = "no action",
        on_delete: str | ReferentialAction = "restrict",
        on_update: str | ReferentialAction = "cascade",
        loading: str | LoadingStrategy = "selectin",
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
        on_save:
            Whether the related records are cascaded when the owner is saved.
            One of ``"cascade"`` or ``"no action"``. Defaults to ``"no action"``.
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
            on_save=on_save,
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
        on_save: SaveAction | str = "no action",
        loading: str | LoadingStrategy = "selectin",
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
        on_save:
            Whether the related record is cascaded when the owner is saved. One
            of ``"cascade"`` or ``"no action"``. Defaults to ``"no action"``.
        loading:
            Strategy used to load the related record. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            target=target,
            local_key=local_key,
            foreign_key=foreign_key,
            on_save=on_save,
            on_delete="no action",
            on_update="no action",
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
        on_save: SaveAction | str = "no action",
        loading: str | LoadingStrategy = "selectin",
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
        on_save:
            Whether the related records are cascaded when the owner is saved.
            One of ``"cascade"`` or ``"no action"``. Defaults to ``"no action"``.
        loading:
            Strategy used to load the related records. One of ``"selectin"``
            or ``"joined"``. Defaults to ``"selectin"``.
        """
        super().__init__(
            target=target,
            local_key=local_key,
            foreign_key=foreign_key,
            on_save=on_save,
            on_delete="cascade",
            on_update="cascade",
            loading=loading,
            kind=RelationshipKind.MANY_TO_MANY,
            is_collection=True,
        )
        self.through = through
