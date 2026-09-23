from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from renus.db import Model
from renus.db.core.exceptions import ValidationError
from renus.db.query.ast import Condition, Path



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
        object.__setattr__(self, "values", values)

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
        object.__setattr__(self, "records", records)

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
        object.__setattr__(self, "values",  values)
        object.__setattr__(self, "filters", filters)

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
        object.__setattr__(self, "values",  values)
        object.__setattr__(self, "filters", filters)

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
