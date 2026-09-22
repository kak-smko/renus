from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from renus.db.core.exceptions import ValidationError
from renus.db.query.ast import Condition, Path


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


def validate_update_values(source: type, values: dict[Any, Any]) -> dict[str, Any]:
    """Normalize and validate a partial update payload for a model.

    Update payloads are partial, so required fields not included in ``values``
    are not checked. Included fields use the same field validation and
    conversion rules as model construction and attribute assignment.
    """
    normalized = normalize_values(values)
    meta = getattr(source, "__db_metadata__", None)
    if meta and meta.timestamps and "updated_at" not in normalized:
        normalized["updated_at"] = datetime.now(timezone.utc)

    field_infos = getattr(source, "_model_fields", None)
    if not field_infos:
        return normalized

    validated: dict[str, Any] = {}
    errors: dict[str, list[str]] = {}
    for name, value in normalized.items():
        field_info = field_infos.get(name)
        if field_info is not None:
            cleaned_value, field_errors = field_info.clean_and_validate(value, source)
            if field_errors:
                errors[name] = field_errors
            else:
                validated[name] = cleaned_value
            continue


        errors[name] = [f"Unknown field '{name}'"]

    if errors:
        raise ValidationError(errors)
    return validated


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

    def __init__(
        self,
        source: type,
        values: dict[Any, Any],
    ) -> None:
        """Build an insert AST with normalized values.

        Parameters
        ----------
        source:
            The model type the insert targets.
        values:
            Field values keyed by path or field name.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "values", normalize_values(values))

    @classmethod
    def from_model(
        cls,
        instance: Any,
    ) -> Insert:
        """Build an insert AST from a model instance's values.

        Parameters
        ----------
        instance:
            Model instance whose fields become the insert values.
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
                        else instance.get_sensitive(fname)
                    )

                    if val is not None or fmeta.nullable:
                        values[fname] = val
        else:
            values = {
                k: v for k, v in instance.__dict__.items() if not k.startswith("_")
            }

        return cls(source=source, values=values)

@dataclass(frozen=True, slots=True)
class InsertMany(MutationAST):
    """Mutation AST representing a multi-row insert."""

    records: tuple[dict[str, Any], ...] = ()

    def __init__(
        self,
        source: type,
        records: Iterable[dict[Any, Any]],
    ) -> None:
        """Build a multi-row insert AST with normalized records.

        Parameters
        ----------
        source:
            The model type the insert targets.
        records:
            Iterable of field-value dicts, one per row.
        """
        object.__setattr__(self, "source", source)
        normalized_records = tuple(normalize_values(r) for r in records)
        object.__setattr__(self, "records", normalized_records)

    @classmethod
    def from_models(
        cls,
        instances: Iterable[Any],
    ) -> InsertMany:
        """Build a multi-row insert AST from model instances.

        Parameters
        ----------
        instances:
            Iterable of model instances to insert.
        """
        inst_list = list(instances)
        if not inst_list:
            raise ValueError("InsertMany.from_models requires at least one model instance")
        source = inst_list[0].__class__
        records = [Insert.from_model(m).values for m in inst_list]
        return cls(source=source, records=records)

@dataclass(frozen=True, slots=True)
class Update(FilterableMutation):
    """Mutation AST representing an update."""

    values: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        source: type,
        values: dict[Any, Any],
        filters: tuple[Condition, ...] = (),
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
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "values", validate_update_values(source, values))
        object.__setattr__(self, "filters", tuple(filters))

    @classmethod
    def from_model(
        cls,
        instance: Any,
    ) -> Update:
        """Build an update AST from a model instance's dirty fields.

        Parameters
        ----------
        instance:
            Model instance providing changed values and identity filters.
        """
        source = instance.__class__
        changes: dict[str, Any] = {}

        meta = getattr(source, "__db_metadata__", None)
        if hasattr(instance, "dirty_fields"):
            for fname in instance.dirty_fields():

                fmeta = meta.fields.get(fname) if meta else None
                changes[fname] = (
                    instance.get_sensitive(fname)
                    if fmeta is not None and fmeta.sensitive
                    else instance.get_sensitive(fname)
                )
        else:
            changes = {
                k: v for k, v in instance.__dict__.items() if not k.startswith("_")
            }

        filters: list[Condition] = []
        if hasattr(instance, "identity_dict"):
            for pk_name, pk_val in instance.identity_dict().items():
                filters.append(Path(source, (pk_name,)) == pk_val)

        return cls(
            source=source,
            values=changes,
            filters=tuple(filters),
        )

@dataclass(frozen=True, slots=True)
class UpdateMany(FilterableMutation):
    """Mutation AST representing a bulk update."""

    values: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        source: type,
        values: dict[Any, Any],
        filters: tuple[Condition, ...] = (),
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
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "values", validate_update_values(source, values))
        object.__setattr__(self, "filters", tuple(filters))

@dataclass(frozen=True, slots=True)
class Delete(FilterableMutation):
    """Mutation AST representing a delete."""

    def __init__(
        self,
        source: type,
        filters: tuple[Condition, ...] = (),
    ) -> None:
        """Build a delete AST.

        Parameters
        ----------
        source:
            The model type the delete targets.
        filters:
            Conditions selecting rows to delete. Defaults to empty.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "filters", tuple(filters))

    @classmethod
    def from_model(
        cls,
        instance: Any,
    ) -> Delete:
        """Build a delete AST from a model instance's identity.

        Parameters
        ----------
        instance:
            Model instance identifying the row to delete.
        """
        source = instance.__class__
        filters: list[Condition] = []
        if hasattr(instance, "identity_dict"):
            for pk_name, pk_val in instance.identity_dict().items():
                filters.append(Path(source, (pk_name,)) == pk_val)

        return cls(source=source, filters=tuple(filters))

@dataclass(frozen=True, slots=True)
class DeleteMany(FilterableMutation):
    """Mutation AST representing a bulk delete."""

    def __init__(
        self,
        source: type,
        filters: tuple[Condition, ...] = (),
    ) -> None:
        """Build a bulk delete AST.

        Parameters
        ----------
        source:
            The model type the delete targets.
        filters:
            Conditions selecting rows to delete. Defaults to empty.
        """
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "filters", tuple(filters))
