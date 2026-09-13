from __future__ import annotations

from dataclasses import replace
from typing import Any, Generic, TypeVar

from renus.db.core.exceptions import ConfigurationError
from renus.db.query.ast import (
    Aggregate,
    Condition,
    HavingCondition,
    Include,
    Operator,
    Ordering,
    Path,
    Projection,
    QueryAST,
)

__all__ = [
    "AggregateFn",
    "Avg",
    "Count",
    "Max",
    "Min",
    "Query",
    "Sum",
]

T = TypeVar("T")

class AggregateFn:
    """A pending aggregate function that can be aliased or compared."""

    def __init__(
        self,
        function: str,
        path: Path | None = None,
        distinct: bool = False,
    ) -> None:
        """Configure an aggregate function.

        Parameters
        ----------
        function:
            The aggregate function name (e.g. count, sum, avg).
        path:
            The field the aggregate is applied to. Defaults to None.
        distinct:
            Whether to count only distinct values. Defaults to False.
        """
        self.function = function
        self.path = path
        self.distinct = distinct

    def as_(self, alias: str) -> Aggregate:
        """Return this aggregate bound to the given result alias."""
        return Aggregate(
            function=self.function,
            path=self.path,
            alias=alias,
            distinct=self.distinct,
        )

    def _cmp(self, op: Operator, value: Any) -> HavingCondition:
        return HavingCondition(op, self, value)

    def __eq__(self, value: object) -> HavingCondition:
        return self._cmp(Operator.EQ, value)

    def __ne__(self, value: object) -> HavingCondition:
        return self._cmp(Operator.NE, value)

    def __gt__(self, value: Any) -> HavingCondition:
        return self._cmp(Operator.GT, value)

    def __ge__(self, value: Any) -> HavingCondition:
        return self._cmp(Operator.GE, value)

    def __lt__(self, value: Any) -> HavingCondition:
        return self._cmp(Operator.LT, value)

    def __le__(self, value: Any) -> HavingCondition:
        return self._cmp(Operator.LE, value)

def Count(path: Path | None = None, *, distinct: bool = False) -> AggregateFn:
    """Create a count aggregate over an optional field."""
    return AggregateFn("count", path, distinct=distinct)

def Sum(path: Path, *, distinct: bool = False) -> AggregateFn:
    """Create a sum aggregate over a field."""
    return AggregateFn("sum", path, distinct=distinct)

def Avg(path: Path, *, distinct: bool = False) -> AggregateFn:
    """Create an average aggregate over a field."""
    return AggregateFn("avg", path, distinct=distinct)

def Min(path: Path) -> AggregateFn:
    """Create a minimum aggregate over a field."""
    return AggregateFn("min", path)

def Max(path: Path) -> AggregateFn:
    """Create a maximum aggregate over a field."""
    return AggregateFn("max", path)

class Query(Generic[T]):
    """An immutable query builder that yields results from a repository."""

    model: type[T]
    repository: Any
    ast: QueryAST

    def __init__(
        self,
        source_or_repository: type[T] | Any,
        ast: QueryAST | None = None,
    ) -> None:
        """Bind a query to a model or repository.

        Parameters
        ----------
        source_or_repository:
            The model type or repository to query against.
        ast:
            Initial query AST. Defaults to an empty query over the source.
        """
        if isinstance(source_or_repository, type):
            object.__setattr__(self, "model", source_or_repository)
            self.repository = None
            self.ast = ast or QueryAST(source=self.model)
        else:
            self.repository = source_or_repository
            object.__setattr__(self, "model", getattr(source_or_repository, "model", object))
            self.ast = ast or QueryAST(source=self.model)

    def _clone(self, **kwargs: Any) -> Query[T]:
        new_ast = replace(self.ast, **kwargs)
        target = self.repository if self.repository is not None else self.model
        return Query(target, ast=new_ast)

    def where(self, *conditions: Condition) -> Query[T]:
        """Return a new query with the given filter conditions added."""
        return self._clone(filters=self.ast.filters + tuple(conditions))

    def filter(self, *conditions: Condition) -> Query[T]:
        """Alias of where; return a new query with the conditions added."""
        return self.where(*conditions)

    __call__ = where

    def select(self, *paths: Path) -> Query[T]:
        """Return a new query selecting only the given fields."""
        return self._clone(projection=Projection(tuple(paths)))

    def order_by(self, *items: Ordering | Path) -> Query[T]:
        """Return a new query sorted by the given orderings."""
        normalized = tuple(i if isinstance(i, Ordering) else Ordering(i) for i in items)
        return self._clone(ordering=self.ast.ordering + normalized)

    def offset(self, n: int) -> Query[T]:
        """Return a new query skipping the first n rows."""
        return self._clone(offset=n)

    def limit(self, n: int) -> Query[T]:
        """Return a new query limited to n rows."""
        return self._clone(limit=n)

    def paginate(self, page: int, size: int) -> Query[T]:
        """Return a new query scoped to a page of the given size."""
        offset_val = max(0, page - 1) * size
        return self._clone(offset=offset_val, limit=size)

    def cursor(self, token: Any, field: Path | None = None) -> Query[T]:
        """Return a new query starting after the given cursor token."""
        return self._clone(cursor=token, cursor_field=field)

    def include(self, *paths: Path | Include) -> Query[T]:
        """Return a new query that eagerly loads the given relations."""
        normalized = tuple(p if isinstance(p, Include) else Include(p) for p in paths)
        return self._clone(includes=self.ast.includes + normalized)

    def group_by(self, *paths: Path) -> Query[T]:
        """Return a new query grouped by the given fields."""
        return self._clone(group_by=self.ast.group_by + tuple(paths))

    def having(self, *conditions: Condition | HavingCondition) -> Query[T]:
        """Return a new query filtered by the given aggregate conditions."""
        return self._clone(having=self.ast.having + tuple(conditions))

    def aggregate(
        self,
        *aggregates: Aggregate | AggregateFn,
        **named: AggregateFn,
    ) -> Query[T]:
        """Return a new query computing the given aggregates."""
        vals: list[Aggregate] = []
        for agg in aggregates:
            if isinstance(agg, AggregateFn):
                alias_name = agg.path.parts[-1] if agg.path else agg.function
                vals.append(agg.as_(f"{agg.function}_{alias_name}"))
            else:
                vals.append(agg)

        for alias, fn in named.items():
            if isinstance(fn, AggregateFn):
                vals.append(fn.as_(alias))

        return self._clone(aggregates=self.ast.aggregates + tuple(vals))

    def distinct(self, val: bool = True) -> Query[T]:
        """Return a new query returning only distinct rows."""
        return self._clone(distinct=val)

    def with_deleted(self) -> Query[T]:
        """Return a new query that includes soft-deleted rows."""
        return self._clone(with_deleted=True, only_deleted=False)

    def only_deleted(self) -> Query[T]:
        """Return a new query matching only soft-deleted rows."""
        return self._clone(with_deleted=True, only_deleted=True)

    async def all(self) -> list[T]:
        """Execute the query and return all matching rows."""
        if self.repository is None:
            raise ConfigurationError("Cannot execute query without a bound repository")
        return await self.repository._query(self.ast)

    async def first(self) -> T | None:
        """Execute the query and return the first matching row, if any."""
        if self.repository is None:
            raise ConfigurationError("Cannot execute query without a bound repository")
        rows = await self.limit(1).all()
        return rows[0] if rows else None

    async def count(self) -> int:
        """Execute the query as a count and return the total rows."""
        if self.repository is None:
            raise ConfigurationError("Cannot execute query without a bound repository")
        return await self.repository._count(self.ast)

    async def exists(self) -> bool:
        """Execute the query and return whether any matching row exists."""
        if self.repository is None:
            raise ConfigurationError("Cannot execute query without a bound repository")
        return await self.repository._exists(self.ast)

