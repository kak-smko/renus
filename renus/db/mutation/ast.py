from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from renus.db.query.ast import Condition, Path

__all__ = [
    "Delete",
    "DeleteMany",
    "FilterableMutation",
    "Insert",
    "InsertMany",
    "MutationAST",
    "Update",
    "UpdateMany",
    "Upsert",
    "delete",
    "delete_many",
    "insert",
    "insert_many",
    "normalize_conflict_target",
    "normalize_values",
    "update",
    "update_many",
    "upsert",
]

def normalize_values(values: dict[Any, Any]) -> dict[str, Any]:
    """Map each value to its final leaf field name."""
    normalized: dict[str, Any] = {}
    for key, val in values.items():
        if isinstance(key, Path):
            normalized[key.parts[-1]] = val
        elif isinstance(key, str):
            normalized[key.split(".")[-1]] = val
        else:
            normalized[str(key)] = val
    return normalized

def normalize_conflict_target(targets: Iterable[Path | str]) -> tuple[str, ...]:
    """Extract the leaf field names from the given conflict targets."""
    normalized: list[str] = []
    for t in targets:
        if isinstance(t, Path):
            normalized.append(t.parts[-1])
        else:
            normalized.append(str(t).split(".")[-1])
    return tuple(normalized)

@dataclass(frozen=True, slots=True)
class MutationAST:
    """Base AST node describing a mutation over a source type."""

    source: type

    @property
    def model_name(self) -> str:
        """Return the name of the source model."""
        return getattr(self.source, "__name__", str(self.source))

@dataclass(frozen=True, slots=True)
class FilterableMutation(MutationAST):
    """Mutation AST that supports filter conditions."""

    filters: tuple[Condition, ...] = ()

    def where(self, *conditions: Condition) -> Any:
        """Return a copy with the given filter conditions added."""
        return replace(self, filters=self.filters + tuple(conditions))

@dataclass(frozen=True, slots=True)
class Insert(MutationAST):
    """Mutation AST representing a single row insert."""

    values: dict[str, Any] = field(default_factory=dict)
    returning: tuple[str, ...] | None = None

    def __init__(
        self,
        source: type,
        values: dict[Any, Any],
        returning: Iterable[Path | str] | None = None,
    ) -> None:
        """Build an insert AST with normalized values.

        Parameters
        ----------
        source:
            The model type the insert targets.
        values:
            Field values keyed by path or field name.
        returning:
            Optional fields to return on insert.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "values", normalize_values(values))
        ret = normalize_conflict_target(returning) if returning is not None else None
        object.__setattr__(self, "returning", ret)

    @classmethod
    def from_model(
        cls,
        instance: Any,
        returning: Iterable[Path | str] | None = None,
    ) -> Insert:
        """Build an insert AST from a model instance's values.

        Parameters
        ----------
        instance:
            Model instance whose fields become the insert values.
        returning:
            Optional fields to return on insert.
        """
        source = instance.__class__
        meta = getattr(source, "__db_metadata__", None)
        values: dict[str, Any] = {}

        if meta:
            for fname, fmeta in meta.fields.items():
                if fmeta.generated and getattr(instance, fname, None) is None:
                    continue
                if hasattr(instance, fname):

                    val = (
                        instance.get_sensitive(fname)
                        if fmeta.sensitive
                        else getattr(instance, fname)
                    )
                    if val is not None:
                        values[fname] = val
        else:
            values = {
                k: v for k, v in instance.__dict__.items() if not k.startswith("_")
            }

        return cls(source=source, values=values, returning=returning)

@dataclass(frozen=True, slots=True)
class InsertMany(MutationAST):
    """Mutation AST representing a multi-row insert."""

    records: tuple[dict[str, Any], ...] = ()
    returning: tuple[str, ...] | None = None

    def __init__(
        self,
        source: type,
        records: Iterable[dict[Any, Any]],
        returning: Iterable[Path | str] | None = None,
    ) -> None:
        """Build a multi-row insert AST with normalized records.

        Parameters
        ----------
        source:
            The model type the insert targets.
        records:
            Iterable of field-value dicts, one per row.
        returning:
            Optional fields to return on insert.
        """
        object.__setattr__(self, "source", source)
        normalized_records = tuple(normalize_values(r) for r in records)
        object.__setattr__(self, "records", normalized_records)
        ret = normalize_conflict_target(returning) if returning is not None else None
        object.__setattr__(self, "returning", ret)

    @classmethod
    def from_models(
        cls,
        instances: Iterable[Any],
        returning: Iterable[Path | str] | None = None,
    ) -> InsertMany:
        """Build a multi-row insert AST from model instances.

        Parameters
        ----------
        instances:
            Iterable of model instances to insert.
        returning:
            Optional fields to return on insert.
        """
        inst_list = list(instances)
        if not inst_list:
            raise ValueError("InsertMany.from_models requires at least one model instance")
        source = inst_list[0].__class__
        records = [Insert.from_model(m).values for m in inst_list]
        return cls(source=source, records=records, returning=returning)

@dataclass(frozen=True, slots=True)
class Update(FilterableMutation):
    """Mutation AST representing an update."""

    values: dict[str, Any] = field(default_factory=dict)
    returning: tuple[str, ...] | None = None

    def __init__(
        self,
        source: type,
        values: dict[Any, Any],
        filters: tuple[Condition, ...] = (),
        returning: Iterable[Path | str] | None = None,
    ) -> None:
        """Build an update AST with normalized values.

        Parameters
        ----------
        source:
            The model type the update targets.
        values:
            Field values to set.
        filters:
            Conditions selecting rows to update. Defaults to empty.
        returning:
            Optional fields to return on update.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "values", normalize_values(values))
        object.__setattr__(self, "filters", tuple(filters))
        ret = normalize_conflict_target(returning) if returning is not None else None
        object.__setattr__(self, "returning", ret)

    @classmethod
    def from_model(
        cls,
        instance: Any,
        returning: Iterable[Path | str] | None = None,
    ) -> Update:
        """Build an update AST from a model instance's dirty fields.

        Parameters
        ----------
        instance:
            Model instance providing changed values and identity filters.
        returning:
            Optional fields to return on update.
        """
        source = instance.__class__
        changes: dict[str, Any] = {}

        meta = getattr(source, "__db_metadata__", None)
        if hasattr(instance, "dirty_fields"):
            for fname in instance.dirty_fields:

                fmeta = meta.fields.get(fname) if meta else None
                changes[fname] = (
                    instance.get_sensitive(fname)
                    if fmeta is not None and fmeta.sensitive
                    else getattr(instance, fname)
                )
        else:
            changes = {
                k: v for k, v in instance.__dict__.items() if not k.startswith("_")
            }

        filters: list[Condition] = []
        if hasattr(instance, "identity_dict"):
            for pk_name, pk_val in instance.identity_dict.items():
                filters.append(Path(source, (pk_name,)) == pk_val)

        return cls(
            source=source,
            values=changes,
            filters=tuple(filters),
            returning=returning,
        )

@dataclass(frozen=True, slots=True)
class UpdateMany(FilterableMutation):
    """Mutation AST representing a bulk update."""

    values: dict[str, Any] = field(default_factory=dict)
    limit: int | None = None
    returning: tuple[str, ...] | None = None

    def __init__(
        self,
        source: type,
        values: dict[Any, Any],
        filters: tuple[Condition, ...] = (),
        limit: int | None = None,
        returning: Iterable[Path | str] | None = None,
    ) -> None:
        """Build a bulk update AST with normalized values.

        Parameters
        ----------
        source:
            The model type the update targets.
        values:
            Field values to set.
        filters:
            Conditions selecting rows to update. Defaults to empty.
        limit:
            Optional maximum number of rows to update.
        returning:
            Optional fields to return on update.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "values", normalize_values(values))
        object.__setattr__(self, "filters", tuple(filters))
        object.__setattr__(self, "limit", limit)
        ret = normalize_conflict_target(returning) if returning is not None else None
        object.__setattr__(self, "returning", ret)

@dataclass(frozen=True, slots=True)
class Delete(FilterableMutation):
    """Mutation AST representing a delete."""

    returning: tuple[str, ...] | None = None

    def __init__(
        self,
        source: type,
        filters: tuple[Condition, ...] = (),
        returning: Iterable[Path | str] | None = None,
    ) -> None:
        """Build a delete AST.

        Parameters
        ----------
        source:
            The model type the delete targets.
        filters:
            Conditions selecting rows to delete. Defaults to empty.
        returning:
            Optional fields to return on delete.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "filters", tuple(filters))
        ret = normalize_conflict_target(returning) if returning is not None else None
        object.__setattr__(self, "returning", ret)

    @classmethod
    def from_model(
        cls,
        instance: Any,
        returning: Iterable[Path | str] | None = None,
    ) -> Delete:
        """Build a delete AST from a model instance's identity.

        Parameters
        ----------
        instance:
            Model instance identifying the row to delete.
        returning:
            Optional fields to return on delete.
        """
        source = instance.__class__
        filters: list[Condition] = []
        if hasattr(instance, "identity_dict"):
            for pk_name, pk_val in instance.identity_dict.items():
                filters.append(Path(source, (pk_name,)) == pk_val)

        return cls(source=source, filters=tuple(filters), returning=returning)

@dataclass(frozen=True, slots=True)
class DeleteMany(FilterableMutation):
    """Mutation AST representing a bulk delete."""

    limit: int | None = None

    def __init__(
        self,
        source: type,
        filters: tuple[Condition, ...] = (),
        limit: int | None = None,
    ) -> None:
        """Build a bulk delete AST.

        Parameters
        ----------
        source:
            The model type the delete targets.
        filters:
            Conditions selecting rows to delete. Defaults to empty.
        limit:
            Optional maximum number of rows to delete.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "filters", tuple(filters))
        object.__setattr__(self, "limit", limit)

@dataclass(frozen=True, slots=True)
class Upsert(FilterableMutation):
    """Mutation AST representing an upsert."""

    conflict_target: tuple[str, ...] = ()
    create_values: dict[str, Any] = field(default_factory=dict)
    update_values: dict[str, Any] = field(default_factory=dict)
    returning: tuple[str, ...] | None = None

    def __init__(
        self,
        source: type,
        conflict_target: Iterable[Path | str],
        create_values: dict[Any, Any],
        update_values: dict[Any, Any],
        filters: tuple[Condition, ...] = (),
        returning: Iterable[Path | str] | None = None,
    ) -> None:
        """Build an upsert AST with normalized values.

        Parameters
        ----------
        source:
            The model type the upsert targets.
        conflict_target:
            Fields used to detect an already existing row.
        create_values:
            Field values used when inserting.
        update_values:
            Field values used when updating an existing row.
        filters:
            Additional filter conditions. Defaults to empty.
        returning:
            Optional fields to return on upsert.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "conflict_target", normalize_conflict_target(conflict_target))
        object.__setattr__(self, "create_values", normalize_values(create_values))
        object.__setattr__(self, "update_values", normalize_values(update_values))
        object.__setattr__(self, "filters", tuple(filters))
        ret = normalize_conflict_target(returning) if returning is not None else None
        object.__setattr__(self, "returning", ret)

    @classmethod
    def from_model(
        cls,
        instance: Any,
        conflict_target: Iterable[Path | str] | None = None,
        returning: Iterable[Path | str] | None = None,
    ) -> Upsert:
        """Build an upsert AST from a model instance.

        Parameters
        ----------
        instance:
            Model instance providing insert and update values.
        conflict_target:
            Fields used to detect an existing row. Defaults to the model's
            primary key when available.
        returning:
            Optional fields to return on upsert.
        """
        source = instance.__class__
        meta = getattr(source, "__db_metadata__", None)

        targets: Iterable[Path | str]
        if conflict_target is None:
            if meta:
                targets = meta.primary_key_fields
            elif hasattr(instance, "identity_dict"):
                targets = tuple(instance.identity_dict.keys())
            else:
                raise ValueError("Upsert requires conflict_target when model metadata is missing")
        else:
            targets = conflict_target

        insert_ast = Insert.from_model(instance)
        update_values = dict(insert_ast.values)

        target_keys = set(normalize_conflict_target(targets))
        for key in target_keys:
            update_values.pop(key, None)

        return cls(
            source=source,
            conflict_target=targets,
            create_values=insert_ast.values,
            update_values=update_values,
            returning=returning,
        )
