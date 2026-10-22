from __future__ import annotations

from typing import Any

from renus.db.query.ast import (
    LIKE_ESCAPE,
    Condition,
    HavingCondition,
    Logical,
    Operator,
    Include,
    Path,
    QueryAST,
    RelationAny,
)
from renus.db.sql.dialect.base import SQLDialect
from renus.util import to_plural_lower

_ALLOWED_AGGREGATE_FUNCTIONS = frozenset({"count", "sum", "avg", "min", "max"})


class SQLCompiled:

    __slots__ = ("joined", "meta", "params", "root_limit", "root_offset", "sql")

    def __init__(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
        meta: Any = None,
        joined: tuple[dict[str, Any], ...] = (),
        root_limit: int | None = None,
        root_offset: int | None = None,
    ) -> None:
        """Hold a compiled SQL statement and its binding parameters.

        Parameters
        ----------
        sql:
            The generated SQL string.
        params:
            Bound parameters to execute the statement. Defaults to empty.
        meta:
            Optional model metadata.
        """
        self.sql = sql
        self.params = tuple(params)
        self.meta = meta
        self.joined = joined
        self.root_limit = root_limit
        self.root_offset = root_offset

    def __repr__(self) -> str:
        return f"SQLCompiled(sql={self.sql!r}, params={self.params!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SQLCompiled):
            return self.sql == other.sql and self.params == other.params
        return False

class SQLCompiler:

    def __init__(self, dialect: SQLDialect) -> None:
        self._alias_counter = 0
        """Bind the dialect used when compiling queries.

        Parameters
        ----------
        dialect:
            SQL dialect used for quoting and placeholder generation.
        """
        self.dialect = dialect

    def compile(self, ast: QueryAST) -> SQLCompiled:
        """Compile a query AST into SQL."""
        self._alias_counter = 0
        source = ast.source
        meta = getattr(source, "__db_metadata__", None)
        table_name = meta.table if meta else getattr(source, "table", source.__name__.lower())
        quoted_table = self.dialect.quote(table_name)

        params: list[Any] = []
        distinct_clause = "DISTINCT " if ast.distinct else ""
        self._root_model = source
        self._root_ref = "r0"
        joined = self._joined_relationships(ast)
        params.extend(param for spec in joined for param in spec.get("params", ()))
        if not joined:
            self._root_ref = None

        if ast.aggregates:
            select_items: list[str] = [self._path(p) for p in ast.group_by]
            for agg in ast.aggregates:
                fn_name = self._agg_sql_name(agg.function)
                distinct_agg = "DISTINCT " if agg.distinct else ""
                target = self._path(agg.path) if agg.path else "*"
                alias = self.dialect.quote(agg.alias)
                select_items.append(f"{fn_name}({distinct_agg}{target}) AS {alias}")
            select_clause = ", ".join(select_items)
        elif ast.projection:
            select_clause = ", ".join(
                f"{self._path(p)} AS {self.dialect.quote(p.parts[-1])}"
                for p in ast.projection.paths
            )
        else:
            if joined:
                select_parts = [f'{self.dialect.quote("r0")}.*']
                for spec in joined:
                    target_meta = spec["meta"]
                    target_ref = self.dialect.quote(spec["alias"])
                    prefix = spec["prefix"]
                    if target_meta is None:
                        fields = (
                            ("parent_id", "key", "value")
                            if spec.get("raw_kind") == "dict"
                            else ("parent_id", "pos", "value")
                        )
                    else:
                        fields = tuple(
                        name
                        for name, field_meta in target_meta.fields.items()
                        if not (field_meta.primary_key and field_meta.generated)
                    )
                    for field_name in fields:
                        if target_meta is not None:
                            column = self._field_name(target_meta.model, field_name)
                        else:
                            column = field_name
                        alias = self.dialect.quote(f"__renus_joined__{prefix}__{field_name}")
                        select_parts.append(
                            f"{target_ref}.{self.dialect.quote(column)} AS {alias}"
                        )
                select_clause = ", ".join(select_parts)
            else:
                select_clause = "*"

        from_clause = f"{quoted_table} AS {self.dialect.quote('r0')}" if joined else quoted_table
        sql = f"SELECT {distinct_clause}{select_clause} FROM {from_clause}"
        if joined:
            sql += " " + " ".join(spec["join"] for spec in joined)

        clauses: list[str] = []

        if meta and meta.soft_delete:
            del_field = self.dialect.quote(meta.deleted_at_field or "deleted_at")
            if self._root_ref:
                del_field = f"{self.dialect.quote(self._root_ref)}.{del_field}"
            if ast.only_deleted:
                clauses.append(f"{del_field} IS NOT NULL")
            elif not ast.with_deleted:
                clauses.append(f"{del_field} IS NULL")

        for cond in ast.filters:
            s, p = self._condition(cond, table_ref=self._root_ref, model=source)
            clauses.append(s)
            params.extend(p)

        if ast.cursor is not None:
            cursor_path = ast.cursor_field
            if cursor_path is None and meta and meta.primary_key_field:
                cursor_path = Path(source, (meta.primary_key_field,))
            if cursor_path is not None:
                clauses.append(f"{self._column(cursor_path, self._root_ref)} > {self.dialect.placeholder}")
                params.append(ast.cursor)

        if clauses:
            sql += f" WHERE {' AND '.join(clauses)}"

        if ast.group_by:
            group_cols = ", ".join(self._column(p, self._root_ref) for p in ast.group_by)
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
                col = self._column(ord_spec.path, self._root_ref)
                direction = " DESC" if ord_spec.descending else " ASC"
                order_items.append(f"{col}{direction}")
            sql += f" ORDER BY {', '.join(order_items)}"
        elif joined:
            child_order = []
            for spec in joined:
                if not spec.get("collection"):
                    continue
                column = "pos" if spec.get("raw_kind") == "list" else "rowid"
                child_order.append(
                    f"{self.dialect.quote(spec['alias'])}.{self.dialect.quote(column)} ASC"
                )
            if child_order and "sqlite" in type(self.dialect).__name__.lower():
                sql += f" ORDER BY {', '.join(child_order)}"

        if not joined:
            sql = self.dialect.limit_offset(sql, ast.limit, ast.offset)

        return SQLCompiled(
            sql,
            tuple(params),
            meta=meta,
            joined=tuple(joined),
            root_limit=ast.limit if joined else None,
            root_offset=ast.offset if joined else None,
        )

    def _joined_relationships(self, ast: QueryAST) -> list[dict[str, Any]]:
        """Build adapter row metadata and SQL joins for eager relationships."""
        if ast.projection or ast.aggregates:
            return []
        meta = getattr(ast.source, "__db_metadata__", None)
        if meta is None:
            return []

        result: list[dict[str, Any]] = []
        alias_number = 0
        requested: dict[tuple[str, ...], Include] = {
            include.path.parts: include for include in ast.includes
        }
        for name, rel in meta.relationships.items():
            loading = getattr(rel.loading, "value", rel.loading)
            if loading == "joined":
                requested.setdefault((name,), Include(Path(ast.source, (name,))))

        def add(
            model: type,
            owner_ref: str,
            path: tuple[str, ...],
            prefix: str,
            owner_key: str,
        ) -> None:
            nonlocal alias_number
            model_meta = getattr(model, "__db_metadata__", None)
            if model_meta is None:
                return
            for name, rel in model_meta.relationships.items():
                include = requested.get(child_path := (*path, name))
                if include is None and getattr(rel.loading, "value", rel.loading) != "joined":
                    continue
                alias_number += 1
                alias = f"r{alias_number}"
                child_prefix = "__".join(child_path)
                target = rel.target if isinstance(rel.target, type) and rel.target not in (dict, list) else None
                target_meta = getattr(target, "__db_metadata__", None)
                owner_column = (
                    owner_key
                    if owner_key == "parent_id"
                    else self._field_name(model, owner_key)
                )
                owner_pk_ref = f"{owner_ref}.{self.dialect.quote(owner_column)}"

                if target_meta is None:
                    continue
                target_table = self.dialect.quote(target_meta.table)
                target_pk = self.dialect.quote(
                    self._field_name(target, target_meta.primary_key_field)
                )
                kind = getattr(rel.kind, "value", rel.kind)
                if kind == "many_to_one":
                    local = self.dialect.quote(
                        self._field_name(model, rel.foreign_key or f"{name}_id")
                    )
                    join = (
                        f"LEFT JOIN {target_table} AS {self.dialect.quote(alias)} "
                        f"ON {self.dialect.quote(alias)}.{target_pk} = {owner_ref}.{local}"
                    )
                elif kind == "many_to_many":
                    through_alias = f"j{alias_number}"
                    local_col = self.dialect.quote(
                        rel.local_key or f"{to_plural_lower(model_meta.table)}_id"
                    )
                    foreign_col = self.dialect.quote(
                        rel.foreign_key or f"{to_plural_lower(target_meta.table)}_id"
                    )
                    through = self.dialect.quote(str(rel.through))
                    join = (
                        f"LEFT JOIN {through} AS {self.dialect.quote(through_alias)} "
                        f"ON {self.dialect.quote(through_alias)}.{local_col} = {owner_pk_ref} "
                        f"LEFT JOIN {target_table} AS {self.dialect.quote(alias)} "
                        f"ON {self.dialect.quote(alias)}.{target_pk} = "
                        f"{self.dialect.quote(through_alias)}.{foreign_col}"
                    )
                else:
                    local = self.dialect.quote(
                        self._field_name(model, rel.local_key or model_meta.primary_key_field)
                    )
                    foreign = self.dialect.quote(
                        self._field_name(target, rel.foreign_key or f"{to_plural_lower(model_meta.table)}_id")
                    )
                    join = (
                        f"LEFT JOIN {target_table} AS {self.dialect.quote(alias)} "
                        f"ON {self.dialect.quote(alias)}.{foreign} = {owner_ref}.{local}"
                    )

                join_params: list[Any] = []
                if include is not None and include.filter is not None and target is not None:
                    filter_sql, filter_params = self._condition(
                        include.filter,
                        table_ref=self.dialect.quote(alias),
                        model=target,
                    )
                    join += f" AND {filter_sql}"
                    join_params.extend(filter_params)
                spec = {
                    "alias": alias,
                    "collection": bool(rel.is_collection),
                    "join": join,
                    "params": tuple(join_params),
                    "join_parent_path": path,
                    "parent_path": path,
                    "parent_meta": model_meta,
                    "parent_alias": owner_ref,
                    "child_order": (
                        self._field_name(target, target_meta.primary_key_field)
                        if target_meta is not None
                        else "rowid"
                    ),
                    "meta": target_meta,
                    "path": child_path,
                    "prefix": child_prefix,
                }
                result.append(spec)
                if target is not None and include is not None:
                    nested = include.nested
                    if nested:
                        requested.update({(*child_path, item.path.parts[0]): item for item in nested})
                    add(
                        target,
                        self.dialect.quote(alias),
                        child_path,
                        child_prefix,
                        target_meta.primary_key_field,
                    )

        add(ast.source, self.dialect.quote("r0"), (), "", meta.primary_key_field)
        return result

    def _path(self, p: Path, table_ref: str | None = None) -> str:
        if len(p.parts) == 1:
            meta = getattr(p.model, "__db_metadata__", None)
            col = p.parts[0]
            if meta:
                fmeta = meta.fields.get(col)
                if fmeta:
                    col = fmeta.column_name
            quoted = self.dialect.quote(col)
            owner_ref = table_ref
            root_ref = getattr(self, "_root_ref", None)
            if owner_ref is None and root_ref and p.model is getattr(self, "_root_model", None):
                owner_ref = self.dialect.quote(root_ref)
            return f"{owner_ref}.{quoted}" if owner_ref else quoted

        meta = getattr(p.model, "__db_metadata__", None)
        if meta and p.parts[0] in meta.fields:
            base = self.dialect.quote(self._field_name(p.model, p.parts[0]))
            owner_ref = table_ref
            root_ref = getattr(self, "_root_ref", None)
            if owner_ref is None and root_ref and p.model is getattr(self, "_root_model", None):
                owner_ref = self.dialect.quote(root_ref)
            if owner_ref:
                base = f"{owner_ref}.{base}"
            json_path = "$" + "".join(
                f"[{int(part)}]" if part.isdigit() else f".{part}"
                for part in p.parts[1:]
            )
            dialect_name = type(self.dialect).__name__.lower()
            if "mysql" in dialect_name:
                return f"JSON_UNQUOTE(JSON_EXTRACT({base}, '{json_path}'))"
            return f"json_extract({base}, '{json_path}')"

        return self.dialect.quote(".".join(p.parts))

    def _condition(
        self,
        c: Condition,
        *,
        table_ref: str | None = None,
        model: type | None = None,
    ) -> tuple[str, list[Any]]:
        if isinstance(c, RelationAny):
            return self._relation_any_condition(c, table_ref=table_ref)

        if c.path is not None and len(c.path.parts) > 1:
            owner_meta = getattr(c.path.model, "__db_metadata__", None)
            field_meta = owner_meta.fields.get(c.path.parts[0]) if owner_meta else None
            if field_meta is not None and field_meta.storage_type is list:
                element_model = field_meta.model_cls
                element_path = Path(element_model, c.path.parts[1:]) if element_model else None
                if element_path is not None:
                    return self._json_collection_any_condition(
                        RelationAny(
                            Path(c.path.model, (c.path.parts[0],)),
                            Condition(c.operator, element_path, c.value),
                        ),
                        field_meta,
                        table_ref=table_ref,
                    )

        if (
            c.path is not None
            and len(c.path.parts) == 1
            and (field_meta := getattr(c.path.model, "__db_metadata__", None)) is not None
            and (list_field := field_meta.fields.get(c.path.parts[0])) is not None
            and list_field.storage_type is list
        ):
            item_path = Path(c.path.model, ())
            return self._json_collection_any_condition(
                RelationAny(c.path, Condition(c.operator, item_path, c.value)),
                list_field,
                table_ref=table_ref,
            )

        if isinstance(c, Logical):
            if c.operator == Operator.NOT:
                child = c.children[0]
                sql, params = self._condition(child, table_ref=table_ref, model=model)
                if child.path is not None:
                    child_meta = getattr(child.path.model, "__db_metadata__", None)
                    child_field = (
                        child_meta.fields.get(child.path.parts[0])
                        if child_meta and child.path.parts
                        else None
                    )
                    if (
                        child_field is not None
                        and child_field.storage_type in (dict, list)
                        and len(child.path.parts) > 1
                    ):
                        return (
                            f"(NOT ({sql}) OR {self._column(child.path, table_ref)} IS NULL)",
                            params,
                        )
                return f"NOT ({sql})", params

            parts = [
                self._condition(child, table_ref=table_ref, model=model)
                for child in c.children
            ]
            joiner = " AND " if c.operator == Operator.AND else " OR "
            sql = f"({joiner.join(x[0] for x in parts)})"
            params: list[Any] = []
            for x in parts:
                params.extend(x[1])
            return sql, params

        if c.path is not None and self._is_reference_path(c.path):
            return self._reference_condition(c, table_ref=table_ref)

        col = self._column(c.path, table_ref) if c.path else ""
        op = c.operator
        val = c.value


        if op == Operator.EQ:
            if val is None:
                return f"{col} IS NULL", []
            return f"{col} = {self.dialect.placeholder}", [val]

        if op == Operator.NE:
            if val is None:
                return f"{col} IS NOT NULL", []
            nested_json_path = bool(
                c.path
                and len(c.path.parts) > 1
                and getattr(c.path.model, "__db_metadata__", None)
                and c.path.parts[0] in c.path.model.__db_metadata__.fields
                and c.path.model.__db_metadata__.fields[c.path.parts[0]].storage_type in (dict, list)
            )
            if nested_json_path:
                return f"({col} <> {self.dialect.placeholder} OR {col} IS NULL)", [val]
            return f"{col} <> {self.dialect.placeholder}", [val]

        if op == Operator.LIKE:
            return f"{col} LIKE {self.dialect.placeholder} ESCAPE '{LIKE_ESCAPE}'", [val]
        
        op_map = {
            Operator.GT: ">",
            Operator.GE: ">=",
            Operator.LT: "<",
            Operator.LE: "<=",
            Operator.REGEX: "REGEXP",
        }
        if op in op_map:
            return f"{col} {op_map[op]} {self.dialect.placeholder}", [val]

        if op == Operator.IS_NULL:
            return f"{col} IS NULL", []

        if op == Operator.IS_NOT_NULL:
            return f"{col} IS NOT NULL", []

        if op in (Operator.IN, Operator.NOT_IN):
            vals = (
                list(val)
                if isinstance(val, (list, tuple, set))
                else ([] if val is None else [val])
            )
            not_prefix = "NOT " if op == Operator.NOT_IN else ""
            if not vals:
                return ("1=0" if op == Operator.IN else "1=1"), []
            if c.path is not None:
                nested_json = self._nested_json_membership_condition(
                    c.path, op, vals, col, table_ref
                )
                if nested_json is not None:
                    return nested_json
            placeholders = self.dialect.placeholders(len(vals))
            expression = f"{col} {not_prefix}IN ({placeholders})"
            return expression, vals

        if op == Operator.BETWEEN:
            lower, upper = val
            ph = self.dialect.placeholder
            return f"{col} BETWEEN {ph} AND {ph}", [lower, upper]

        raise ValueError(f"Unsupported query condition operator: {op}")

    def _agg_sql_name(self, function: str) -> str:
        """Validate an aggregate function name and return its SQL form.

        Function names are interpolated into SQL, so anything outside the
        allowlist is rejected instead of being rendered.
        """
        fn = function.lower() if isinstance(function, str) else function
        if fn not in _ALLOWED_AGGREGATE_FUNCTIONS:
            raise ValueError(f"Unsupported aggregate function: {function!r}")
        return fn.upper()

    def _new_alias(self, prefix: str) -> str:
        self._alias_counter += 1
        return f"{prefix}{self._alias_counter}"

    @staticmethod
    def _field_name(model: type, name: str) -> str:
        meta = getattr(model, "__db_metadata__", None)
        field_meta = meta.fields.get(name) if meta else None
        return field_meta.column_name if field_meta else name

    def _column(self, path: Path | None, table_ref: str | None = None) -> str:
        if path is None:
            return ""
        if len(path.parts) != 1:
            return self._path(path, table_ref)
        col = self.dialect.quote(self._field_name(path.model, path.parts[0]))
        return f"{table_ref}.{col}" if table_ref else col

    def _is_reference_path(self, path: Path) -> bool:
        if len(path.parts) < 2:
            return False
        meta = getattr(path.model, "__db_metadata__", None)
        return bool(meta and path.parts[0] in meta.relationships)

    def _nested_json_membership_condition(
        self,
        path: Path,
        operator: Operator,
        values: list[Any],
        column: str,
        table_ref: str | None,
    ) -> tuple[str, list[Any]] | None:
        """Compile IN predicates against scalar or array-valued JSON paths."""
        if len(path.parts) < 2:
            return None
        meta = getattr(path.model, "__db_metadata__", None)
        field_meta = meta.fields.get(path.parts[0]) if meta else None
        if field_meta is None or field_meta.storage_type not in (dict, list):
            return None

        base = self.dialect.quote(self._field_name(path.model, path.parts[0]))
        owner_ref = table_ref
        root_ref = getattr(self, "_root_ref", None)
        if owner_ref is None and root_ref and path.model is getattr(self, "_root_model", None):
            owner_ref = self.dialect.quote(root_ref)
        if owner_ref:
            base = f"{owner_ref}.{base}"
        json_path = "$" + "".join(
            f"[{int(part)}]" if part.isdigit() else f".{part}"
            for part in path.parts[1:]
        )
        path_literal = "'" + json_path.replace("'", "''") + "'"
        placeholders = self.dialect.placeholders(len(values))
        dialect_name = type(self.dialect).__name__.lower()

        if "mysql" in dialect_name:
            json_value = f"JSON_EXTRACT({base}, {path_literal})"
            json_type = f"JSON_TYPE({json_value})"
            scalar_value = f"COALESCE({json_type} <> 'ARRAY', TRUE)"
            candidates = [
                "JSON_CONTAINS("
                f"{json_value}, JSON_EXTRACT(JSON_ARRAY({self.dialect.placeholder}), '$[0]'))"
                for _ in values
            ]
            array_match = (
                f"COALESCE(({json_type} = 'ARRAY' AND "
                f"({' OR '.join(candidates)})), FALSE)"
            )
        else:
            json_type = f"json_type({base}, {path_literal})"
            scalar_value = f"COALESCE({json_type} <> 'array', 1)"
            value_expr = f"json_array_item.{self.dialect.quote('value')}"
            array_match = (
                f"COALESCE(({json_type} = 'array' AND EXISTS ("
                f"SELECT 1 FROM json_each({base}, {path_literal}) AS json_array_item "
                f"WHERE {value_expr} IN ({placeholders}))), 0)"
            )

        scalar_match = f"({scalar_value} AND {column} IN ({placeholders}))"
        if operator == Operator.IN:
            return f"({array_match} OR {scalar_match})", [*values, *values]

        scalar_not_match = (
            f"(NOT {scalar_value} OR {column} NOT IN ({placeholders}) "
            f"OR {column} IS NULL)"
        )
        return f"(NOT {array_match} AND {scalar_not_match})", [*values, *values]

    def _relationship_join(
        self,
        owner_model: type,
        rel_name: str,
        owner_ref: str,
        target_alias: str,
    ) -> tuple[str, list[Any], type]:
        owner_meta = owner_model.__db_metadata__
        rel = owner_meta.relationships[rel_name]
        target_model = rel.target
        target_meta = target_model.__db_metadata__
        target_pk = self.dialect.quote(self._field_name(target_model, target_meta.primary_key_field))
        owner_pk = self.dialect.quote(self._field_name(owner_model, owner_meta.primary_key_field))
        target_table = self.dialect.quote(target_meta.table)
        if rel.kind.value == "many_to_one":
            local = self.dialect.quote(self._field_name(owner_model, rel.foreign_key or f"{rel_name}_id"))
            return f"{target_table} {target_alias}", [f"{target_alias}.{target_pk} = {owner_ref}.{local}"], target_model
        if rel.kind.value == "many_to_many":
            through = self.dialect.quote(rel.through)
            through_alias = self._new_alias("j")
            local_col = self.dialect.quote(rel.local_key or f"{to_plural_lower(owner_meta.table)}_id")
            foreign_col = self.dialect.quote(rel.foreign_key or f"{to_plural_lower(target_meta.table)}_id")
            return (
                f"{through} {through_alias} JOIN {target_table} {target_alias} "
                f"ON {target_alias}.{target_pk} = {through_alias}.{foreign_col}",
                [f"{through_alias}.{local_col} = {owner_ref}.{owner_pk}"],
                target_model,
            )
        local_col = self.dialect.quote(self._field_name(owner_model, rel.local_key or owner_meta.primary_key_field))
        foreign_col = self.dialect.quote(self._field_name(target_model, rel.foreign_key or f"{to_plural_lower(owner_meta.table)}_id"))
        return f"{target_table} {target_alias}", [f"{target_alias}.{foreign_col} = {owner_ref}.{local_col}"], target_model

    def _reference_condition(self, c: Condition, *, table_ref: str | None) -> tuple[str, list[Any]]:
        path = c.path
        assert path is not None
        owner_model = path.model
        owner_meta = owner_model.__db_metadata__
        owner_ref = table_ref or self.dialect.quote(owner_meta.table)
        rel_name = path.parts[0]
        alias = self._new_alias("r")
        from_sql, joins, target_model = self._relationship_join(owner_model, rel_name, owner_ref, alias)
        inner_path = Path(target_model, path.parts[1:])
        inner = Condition(c.operator, inner_path, c.value)
        inner_sql, params = self._condition(inner, table_ref=alias, model=target_model)
        predicates = [*joins, inner_sql]
        return f"EXISTS (SELECT 1 FROM {from_sql} WHERE {' AND '.join(predicates)})", params

    def _json_collection_any_condition(
        self,
        relation_any: RelationAny,
        field_meta: Any,
        *,
        table_ref: str | None,
    ) -> tuple[str, list[Any]]:
        owner_model = relation_any.relation.model
        owner_meta = owner_model.__db_metadata__
        owner_ref = table_ref or self.dialect.quote(owner_meta.table)
        field_name = self.dialect.quote(field_meta.column_name)
        field_expr = f"{owner_ref}.{field_name}"
        dialect_name = type(self.dialect).__name__.lower()
        if "mysql" in dialect_name:
            from_sql = (
                f"JSON_TABLE({field_expr}, '$[*]' COLUMNS "
                f"({self.dialect.quote('value')} JSON PATH '$')) AS json_item"
            )
            item_value = f"json_item.{self.dialect.quote('value')}"
        else:
            from_sql = f"json_each({field_expr}) AS json_item"
            item_value = f"json_item.{self.dialect.quote('value')}"

        def compile_condition(condition: Condition) -> tuple[str, list[Any]]:
            def encode(value: Any) -> Any:
                return self.dialect.encode_value(value)

            if isinstance(condition, Logical):
                if condition.operator == Operator.NOT:
                    sql, params = compile_condition(condition.children[0])
                    return f"NOT ({sql})", params
                parts = [compile_condition(child) for child in condition.children]
                joiner = " AND " if condition.operator == Operator.AND else " OR "
                return (
                    f"({joiner.join(sql for sql, _ in parts)})",
                    [param for _, params in parts for param in params],
                )
            if isinstance(condition, RelationAny) or condition.path is None:
                raise ValueError("Nested any() predicates in JSON collection fields are not supported")

            json_path = "$" + "".join(f".{part}" for part in condition.path.parts)
            value_expr = item_value if not condition.path.parts else (
                f"JSON_UNQUOTE(JSON_EXTRACT({item_value}, '{json_path}'))"
                if "mysql" in dialect_name
                else f"json_extract({item_value}, '{json_path}')"
            )
            operator = condition.operator
            value = condition.value
            if operator == Operator.EQ and value is None:
                return f"{value_expr} IS NULL", []
            if operator == Operator.NE and value is None:
                return f"{value_expr} IS NOT NULL", []
            operator_sql = {
                Operator.EQ: "=",
                Operator.NE: "<>",
                Operator.GT: ">",
                Operator.GE: ">=",
                Operator.LT: "<",
                Operator.LE: "<=",
                Operator.LIKE: "LIKE",
                Operator.REGEX: "REGEXP",
            }.get(operator)
            if operator_sql is not None:
                expression = f"{value_expr} {operator_sql} {self.dialect.placeholder}"
                if operator == Operator.NE and value is not None:
                    expression = f"({expression} OR {value_expr} IS NULL)"
                return expression, [encode(value)]
            if operator in (Operator.IN, Operator.NOT_IN):
                values = list(value) if isinstance(value, (list, tuple, set)) else [value]
                if not values:
                    return ("1=0" if operator == Operator.IN else "1=1"), []
                prefix = "NOT " if operator == Operator.NOT_IN else ""
                expression = (
                    f"{value_expr} {prefix}IN ({self.dialect.placeholders(len(values))})"
                )
                if operator == Operator.NOT_IN:
                    expression = f"({expression} OR {value_expr} IS NULL)"
                return expression, [encode(item) for item in values]

            if operator == Operator.BETWEEN:
                lower, upper = value
                return (
                    f"{value_expr} BETWEEN {self.dialect.placeholder} AND {self.dialect.placeholder}",
                    [encode(lower), encode(upper)],
                )
            if operator == Operator.IS_NULL:
                return f"{value_expr} IS NULL", []
            if operator == Operator.IS_NOT_NULL:
                return f"{value_expr} IS NOT NULL", []
            raise ValueError(f"Unsupported JSON collection condition operator: {operator}")

        condition_sql, params = compile_condition(relation_any.condition)
        return f"EXISTS (SELECT 1 FROM {from_sql} WHERE {condition_sql})", params

    def _relation_any_condition(self, c: RelationAny, *, table_ref: str | None) -> tuple[str, list[Any]]:
        owner_meta = getattr(c.relation.model, "__db_metadata__", None)
        if owner_meta and c.relation.parts:
            field_meta = owner_meta.fields.get(c.relation.parts[0])
            if field_meta is not None and field_meta.storage_type is list:
                return self._json_collection_any_condition(
                    c,
                    field_meta,
                    table_ref=table_ref,
                )

        relation = c.relation
        owner_model = relation.model
        owner_meta = owner_model.__db_metadata__
        owner_ref = table_ref or self.dialect.quote(owner_meta.table)
        rel_name = relation.parts[0]
        alias = self._new_alias("r")
        from_sql, joins, target_model = self._relationship_join(owner_model, rel_name, owner_ref, alias)
        sub_sql, params = self._condition(c.condition, table_ref=alias, model=target_model)
        return f"EXISTS (SELECT 1 FROM {from_sql} WHERE {' AND '.join([*joins, sub_sql])})", params


    def _having_condition(self, h: Any) -> tuple[str, list[Any]]:
        if isinstance(h, HavingCondition) and h.operator in (Operator.AND, Operator.OR):
            children = h.aggregate if isinstance(h.aggregate, tuple) else ()
            parts = [self._having_condition(child) for child in children]
            joiner = " AND " if h.operator == Operator.AND else " OR "
            sql = f"({joiner.join(part[0] for part in parts)})"
            params: list[Any] = []
            for _, child_params in parts:
                params.extend(child_params)
            return sql, params

        if isinstance(h, Logical):
            parts = [self._having_condition(child) for child in h.children]
            joiner = " AND " if h.operator == Operator.AND else " OR "
            sql = f"({joiner.join(part[0] for part in parts)})"
            params: list[Any] = []
            for _, child_params in parts:
                params.extend(child_params)
            if h.operator == Operator.NOT:
                child_sql, child_params = parts[0]
                return f"NOT ({child_sql})", child_params
            return sql, params

        if isinstance(h, HavingCondition):
            agg = h.aggregate
            fn_name = self._agg_sql_name(agg.function)
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
