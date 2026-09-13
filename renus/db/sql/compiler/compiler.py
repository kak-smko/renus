from __future__ import annotations

from typing import Any

from renus.db.query.ast import (
    Condition,
    HavingCondition,
    Logical,
    Operator,
    Path,
    QueryAST,
    RelationAny,
)
from renus.db.sql.dialect.base import SQLDialect

__all__ = ["SQLCompiled", "SQLCompiler"]

class SQLCompiled:

    __slots__ = ("params", "sql")

    def __init__(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        """Hold a compiled SQL statement and its binding parameters.

        Parameters
        ----------
        sql:
            The generated SQL string.
        params:
            Bound parameters to execute the statement. Defaults to empty.
        """
        self.sql = sql
        self.params = tuple(params)

    def __repr__(self) -> str:
        return f"SQLCompiled(sql={self.sql!r}, params={self.params!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SQLCompiled):
            return self.sql == other.sql and self.params == other.params
        return False

class SQLCompiler:

    def __init__(self, dialect: SQLDialect) -> None:
        """Bind the dialect used when compiling queries.

        Parameters
        ----------
        dialect:
            SQL dialect used for quoting and placeholder generation.
        """
        self.dialect = dialect

    def compile(self, ast: QueryAST) -> SQLCompiled:
        """Compile a query AST into SQL."""
        source = ast.source
        meta = getattr(source, "__db_metadata__", None)
        table_name = meta.table if meta else getattr(source, "table", source.__name__.lower())
        quoted_table = self.dialect.quote(table_name)

        params: list[Any] = []
        distinct_clause = "DISTINCT " if ast.distinct else ""

        if ast.aggregates:
            select_items: list[str] = [self._path(p) for p in ast.group_by]
            for agg in ast.aggregates:
                fn_name = agg.function.upper()
                distinct_agg = "DISTINCT " if agg.distinct else ""
                target = self._path(agg.path) if agg.path else "*"
                alias = self.dialect.quote(agg.alias)
                select_items.append(f"{fn_name}({distinct_agg}{target}) AS {alias}")
            select_clause = ", ".join(select_items)
        elif ast.projection:
            select_clause = ", ".join(self._path(p) for p in ast.projection.paths)
        else:
            select_clause = "*"

        sql = f"SELECT {distinct_clause}{select_clause} FROM {quoted_table}"

        clauses: list[str] = []

        if meta and meta.soft_delete:
            del_field = self.dialect.quote(meta.deleted_at_field or "deleted_at")
            if ast.only_deleted:
                clauses.append(f"{del_field} IS NOT NULL")
            elif not ast.with_deleted:
                clauses.append(f"{del_field} IS NULL")

        for cond in ast.filters:
            s, p = self._condition(cond)
            clauses.append(s)
            params.extend(p)

        if clauses:
            sql += f" WHERE {' AND '.join(clauses)}"

        if ast.group_by:
            group_cols = ", ".join(self._path(p) for p in ast.group_by)
            sql += f" GROUP BY {group_cols}"

        if ast.having:
            having_clauses: list[str] = []
            for h in ast.having:
                hs, hp = self._having_condition(h)
                having_clauses.append(hs)
                params.extend(hp)
            sql += f" HAVING {' AND '.join(having_clauses)}"

        if ast.ordering:
            order_items: list[str] = []
            for ord_spec in ast.ordering:
                col = self._path(ord_spec.path)
                direction = " DESC" if ord_spec.descending else " ASC"
                nulls = ""
                if ord_spec.nulls_first:
                    nulls = " NULLS FIRST"
                elif ord_spec.nulls_last:
                    nulls = " NULLS LAST"
                order_items.append(f"{col}{direction}{nulls}")
            sql += f" ORDER BY {', '.join(order_items)}"

        sql = self.dialect.limit_offset(sql, ast.limit, ast.offset)

        return SQLCompiled(sql, tuple(params))

    def _path(self, p: Path) -> str:
        if len(p.parts) == 1:
            meta = getattr(p.model, "__db_metadata__", None)
            col = p.parts[0]
            if meta:
                fmeta = meta.fields.get(col)
                if fmeta:
                    col = fmeta.column_name
            return self.dialect.quote(col)

        meta = getattr(p.model, "__db_metadata__", None)
        if meta:
            rel_name = p.parts[0]
            rel = meta.relationships.get(rel_name)
            if rel and rel.is_embedded:

                parent_table = self.dialect.quote(meta.table)
                parent_pk = self.dialect.quote(meta.primary_key_field)
                embedded_table = self.dialect.quote(f"{meta.table}_{rel_name}")
                target_field = self.dialect.quote(p.parts[-1])
                parent_fk = self.dialect.quote("parent_id")
                return (
                    f"(SELECT e.{target_field} FROM {embedded_table} e "
                    f"WHERE e.{parent_fk} = {parent_table}.{parent_pk})"
                )

        return self.dialect.quote(".".join(p.parts))

    def _condition(self, c: Condition) -> tuple[str, list[Any]]:
        if isinstance(c, RelationAny):
            parent_meta = getattr(c.relation.model, "__db_metadata__", None)
            rel_name = c.relation.parts[0]
            rel = parent_meta.relationships[rel_name] if parent_meta else None
            target_meta = getattr(rel.target, "__db_metadata__", None) if rel else None

            parent_table = self.dialect.quote(parent_meta.table if parent_meta else "parents")
            child_table = self.dialect.quote(target_meta.table if target_meta else "children")
            parent_pk = self.dialect.quote(parent_meta.primary_key_field if parent_meta else "id")
            fk = self.dialect.quote(rel.foreign_key or "parent_id") if rel else self.dialect.quote("parent_id")

            sub_sql, sub_params = self._condition(c.condition)
            if c.condition.path and len(c.condition.path.parts) == 1:
                target_col = self.dialect.quote(c.condition.path.parts[0])
                sub_sql = sub_sql.replace(target_col, f"e.{target_col}")

            sql = (
                f"EXISTS (SELECT 1 FROM {child_table} e "
                f"WHERE e.{fk} = {parent_table}.{parent_pk} AND {sub_sql})"
            )
            return sql, sub_params

        if isinstance(c, Logical):
            if c.operator == Operator.NOT:
                s, p = self._condition(c.children[0])
                return f"NOT ({s})", p

            parts = [self._condition(child) for child in c.children]
            joiner = " AND " if c.operator == Operator.AND else " OR "
            sql = f"({joiner.join(x[0] for x in parts)})"
            params: list[Any] = []
            for x in parts:
                params.extend(x[1])
            return sql, params

        col = self._path(c.path) if c.path else ""
        op = c.operator
        val = c.value

        if c.path is not None and op in (Operator.EQ, Operator.NE, Operator.IN, Operator.NOT_IN):
            raw_cond = self._raw_dict_condition(c, op)
            if raw_cond is not None:
                return raw_cond

        if op == Operator.EQ:
            if val is None:
                return f"{col} IS NULL", []
            return f"{col} = {self.dialect.placeholder}", [val]

        if op == Operator.NE:
            if val is None:
                return f"{col} IS NOT NULL", []
            return f"{col} <> {self.dialect.placeholder}", [val]

        op_map = {
            Operator.GT: ">",
            Operator.GE: ">=",
            Operator.LT: "<",
            Operator.LE: "<=",
            Operator.LIKE: "LIKE",
            Operator.REGEX: "REGEXP",
        }
        if op in op_map:
            return f"{col} {op_map[op]} {self.dialect.placeholder}", [val]

        if op == Operator.IS_NULL:
            return f"{col} IS NULL", []

        if op == Operator.IS_NOT_NULL:
            return f"{col} IS NOT NULL", []

        if op in (Operator.IN, Operator.NOT_IN):
            vals = list(val) if val is not None else []
            not_prefix = "NOT " if op == Operator.NOT_IN else ""
            if not vals:
                return ("1=0" if op == Operator.IN else "1=1"), []
            placeholders = self.dialect.placeholders(len(vals))
            return f"{col} {not_prefix}IN ({placeholders})", vals

        if op == Operator.BETWEEN:
            lower, upper = val
            ph = self.dialect.placeholder
            return f"{col} BETWEEN {ph} AND {ph}", [lower, upper]

        raise ValueError(f"Unsupported query condition operator: {op}")

    def _raw_dict_condition(self, c: Condition, op: Operator) -> tuple[str, list[Any]] | None:
        if c.path is None:
            return None
        paths = c.path.parts
        meta = getattr(c.path.model, "__db_metadata__", None)
        if meta is None:
            return None
        rel = meta.relationships.get(paths[0])
        if rel is None or not rel.is_embedded:
            return None

        parent_table = self.dialect.quote(meta.table)
        parent_pk = self.dialect.quote(meta.primary_key_field)
        e_table = self.dialect.quote(f"{meta.table}_{paths[0]}")
        pid = self.dialect.quote("parent_id")
        rest = paths[1:]

        if rel.target is dict:
            if not rest:
                return None
            key_col = self.dialect.quote("key")
            fixed_key = (f"e.{key_col} = {self.dialect.placeholder}", [rest[0]])
            return self._embed_sub_exists(
                e_table, pid, parent_table, parent_pk, "value", op, c.value,
                fixed_key=fixed_key, string_values=True,
            )

        if rel.target is list:
            return self._embed_sub_exists(
                e_table, pid, parent_table, parent_pk, "value", op, c.value,
                string_values=True,
            )

        child_meta = getattr(rel.target, "__db_metadata__", None) \
            if isinstance(rel.target, type) else None
        if child_meta is None:
            return None
        col_name = rest[0] if rest else ""
        fmeta = child_meta.fields.get(col_name)
        col = self.dialect.quote(fmeta.column_name if fmeta else col_name)
        return self._embed_sub_exists(
            e_table, pid, parent_table, parent_pk, col, op, c.value,
        )

    def _embed_sub_exists(
        self,
        e_table: str,
        pid: str,
        parent_table: str,
        parent_pk: str,
        col: str,
        op: Operator,
        value: Any,
        *,
        fixed_key: tuple[str, list[Any]] | None = None,
        string_values: bool = False,
    ) -> tuple[str, list[Any]] | None:
        def enc(v: Any) -> Any:
            return str(v) if string_values else v

        if op == Operator.EQ and isinstance(value, list) and string_values:
            clauses: list[str] = []
            params: list[Any] = []
            for v in value:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM {e_table} e WHERE e.{pid} = "
                    f"{parent_table}.{parent_pk} AND e.{col} = "
                    f"{self.dialect.placeholder})"
                )
                params.append(enc(v))
            return f"( { ' AND '.join(clauses) } )", params

        if op in (Operator.IN, Operator.NOT_IN):
            vals = list(value) if isinstance(value, list) else [value]
            if not vals:
                return ("1=0" if op == Operator.IN else "1=1"), []
            not_prefix = "NOT " if op == Operator.NOT_IN else ""
            placeholders = self.dialect.placeholders(len(vals))
            expr = f"e.{col} {not_prefix}IN ({placeholders})"
        else:
            op_str = "<>" if op == Operator.NE else "="
            expr = f"e.{col} {op_str} {self.dialect.placeholder}"
            vals = [value]

        inner = f"e.{pid} = {parent_table}.{parent_pk}"
        params = []
        if fixed_key:
            inner += f" AND {fixed_key[0]}"
            params.extend(fixed_key[1])
        params.extend(enc(v) for v in vals)
        return f"EXISTS (SELECT 1 FROM {e_table} e WHERE {inner} AND {expr})", params

    def _having_condition(self, h: Any) -> tuple[str, list[Any]]:
        if isinstance(h, HavingCondition):
            agg = h.aggregate
            fn_name = agg.function.upper()
            target = self._path(agg.path) if agg.path else "*"
            distinct_str = "DISTINCT " if agg.distinct else ""
            expr = f"{fn_name}({distinct_str}{target})"

            op_map = {
                Operator.EQ: "=",
                Operator.NE: "<>",
                Operator.GT: ">",
                Operator.GE: ">=",
                Operator.LT: "<",
                Operator.LE: "<=",
            }
            op_str = op_map.get(h.operator, "=")
            return f"{expr} {op_str} {self.dialect.placeholder}", [h.value]

        if isinstance(h, Condition):
            return self._condition(h)

        return str(h), []
