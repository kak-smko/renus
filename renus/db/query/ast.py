from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "Aggregate",
    "Condition",
    "GroupBy",
    "HavingCondition",
    "Include",
    "Logical",
    "Operator",
    "Ordering",
    "Path",
    "Projection",
    "Q",
    "QueryAST",
    "RelationAny",
]

class Operator(str, Enum):
    """Comparison and logical operators used in query conditions."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"
    IN = "in"
    NOT_IN = "not_in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    LIKE = "like"
    REGEX = "regex"
    BETWEEN = "between"
    AND = "and"
    OR = "or"
    NOT = "not"

@dataclass(frozen=True, slots=True)
class Path:
    """A typed field reference that supports fluent condition and ordering builds."""

    model: type
    parts: tuple[str, ...]

    def __str__(self) -> str:
        return ".".join(self.parts)

    def __repr__(self) -> str:
        model_name = getattr(self.model, "__name__", str(self.model))
        return f"Path({model_name}, {self.parts})"

    def __hash__(self) -> int:
        return hash((self.model, self.parts))

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            return self
        if self.parts:
            return instance.__dict__.get(self.parts[-1], None)
        return None

    def __getattr__(self, name: str) -> Path:
        if name.startswith("_"):
            raise AttributeError(name)
        return Path(self.model, (*self.parts, name))

    def _cmp(self, op: Operator, v: Any = None) -> Condition:
        return Condition(op, self, v)

    def __eq__(self, v: object) -> Condition:
        return self._cmp(Operator.EQ, v)

    def __ne__(self, v: object) -> Condition:
        return self._cmp(Operator.NE, v)

    def __gt__(self, v: Any) -> Condition:
        return self._cmp(Operator.GT, v)

    def __ge__(self, v: Any) -> Condition:
        return self._cmp(Operator.GE, v)

    def __lt__(self, v: Any) -> Condition:
        return self._cmp(Operator.LT, v)

    def __le__(self, v: Any) -> Condition:
        return self._cmp(Operator.LE, v)

    def in_(self, v: Any) -> Condition:
        """Return a condition testing that the field is in the given values."""
        return self._cmp(Operator.IN, v)

    def not_in(self, v: Any) -> Condition:
        """Return a condition testing that the field is not in the given values."""
        return self._cmp(Operator.NOT_IN, v)

    def is_null(self) -> Condition:
        """Return a condition testing that the field is null."""
        return self._cmp(Operator.IS_NULL)

    def is_not_null(self) -> Condition:
        """Return a condition testing that the field is not null."""
        return self._cmp(Operator.IS_NOT_NULL)

    def like(self, pattern: str) -> Condition:
        """Return a condition matching the field against a SQL LIKE pattern."""
        return self._cmp(Operator.LIKE, pattern)

    def regex(self, pattern: str) -> Condition:
        """Return a condition matching the field against a regular expression."""
        return self._cmp(Operator.REGEX, pattern)

    def between(self, lower: Any, upper: Any) -> Condition:
        """Return a condition testing that the field is within the given range."""
        return self._cmp(Operator.BETWEEN, (lower, upper))

    def any(self, condition: Condition) -> RelationAny:
        """Return a condition matching any related record for this field."""
        return RelationAny(self, condition)

    def asc(
        self,
        *,
        nulls_first: bool = False,
        nulls_last: bool = False,
    ) -> Ordering:
        """Return an ascending ordering for this field."""
        return Ordering(
            self,
            descending=False,
            nulls_first=nulls_first,
            nulls_last=nulls_last,
        )

    def desc(
        self,
        *,
        nulls_first: bool = False,
        nulls_last: bool = False,
    ) -> Ordering:
        """Return a descending ordering for this field."""
        return Ordering(
            self,
            descending=True,
            nulls_first=nulls_first,
            nulls_last=nulls_last,
        )

@dataclass(frozen=True, slots=True)
class Condition:
    """A single comparison or logical condition on a field."""

    operator: Operator
    path: Path | None = None
    value: Any = None

    def __and__(self, o: Condition) -> Logical:
        return Logical(Operator.AND, (self, o))

    def __or__(self, o: Condition) -> Logical:
        return Logical(Operator.OR, (self, o))

    def __invert__(self) -> Logical:
        return Logical(Operator.NOT, (self,))

@dataclass(frozen=True, slots=True)
class Logical(Condition):
    """A logical combination of child conditions."""

    children: tuple[Condition, ...] = field(default_factory=tuple)

    def __init__(self, operator: Operator, children: tuple[Condition, ...]) -> None:
        """Build a logical condition combining the given children.

        Parameters
        ----------
        operator:
            The logical operator (e.g. AND, OR, NOT).
        children:
            The child conditions to combine.
        """
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "children", tuple(children))
        object.__setattr__(self, "path", None)
        object.__setattr__(self, "value", None)

class Q(Condition):
    """Factory combining conditions with a logical AND."""

    def __new__(cls, *conditions: Condition) -> Condition:
        if not conditions:
            raise ValueError("Q() requires at least one condition argument")
        if len(conditions) == 1:
            return conditions[0]
        return Logical(Operator.AND, conditions)

@dataclass(frozen=True, slots=True)
class RelationAny(Condition):
    """A condition matching any related record meeting a sub-condition."""

    relation: Path = field(default=None)
    condition: Condition = field(default=None)

    def __init__(self, relation: Path, condition: Condition) -> None:
        """Build a relation-matching condition.

        Parameters
        ----------
        relation:
            The relation path to match against.
        condition:
            The sub-condition that related records must satisfy.
        """
        object.__setattr__(self, "operator", Operator.AND)
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "condition", condition)
        object.__setattr__(self, "path", relation)
        object.__setattr__(self, "value", condition)

@dataclass(frozen=True, slots=True)
class Ordering:
    """Sort direction and null policy for a field."""

    path: Path
    descending: bool = False
    nulls_first: bool = False
    nulls_last: bool = False

@dataclass(frozen=True, slots=True)
class Projection:
    """The set of fields selected for a query."""

    paths: tuple[Path, ...]

@dataclass(frozen=True, slots=True)
class Include:
    """A relationship to eagerly load, with optional nested includes."""

    path: Path
    nested: tuple[Include, ...] = ()
    filter: Condition | None = None

@dataclass(frozen=True, slots=True)
class GroupBy:
    """The fields a query is grouped by."""

    paths: tuple[Path, ...]

@dataclass(frozen=True, slots=True)
class Aggregate:
    """An aggregate function applied to a field under an alias."""

    function: str
    path: Path | None
    alias: str
    distinct: bool = False

@dataclass(frozen=True, slots=True)
class HavingCondition:
    """A comparison against an aggregate result."""

    operator: Operator
    aggregate: Any
    value: Any

    def __and__(self, o: HavingCondition) -> HavingCondition:
        return HavingCondition(Operator.AND, (self, o), None)

    def __or__(self, o: HavingCondition) -> HavingCondition:
        return HavingCondition(Operator.OR, (self, o), None)

@dataclass(frozen=True, slots=True)
class QueryAST:
    """The full parsed structure of a query."""

    source: type
    filters: tuple[Condition, ...] = ()
    projection: Projection | None = None
    ordering: tuple[Ordering, ...] = ()
    offset: int | None = None
    limit: int | None = None
    cursor: Any = None
    cursor_field: Path | None = None
    includes: tuple[Include, ...] = ()
    aggregates: tuple[Aggregate, ...] = ()
    group_by: tuple[Path, ...] = ()
    having: tuple[Condition | HavingCondition, ...] = ()
    with_deleted: bool = False
    only_deleted: bool = False
    distinct: bool = False
