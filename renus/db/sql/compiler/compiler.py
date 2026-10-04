from __future__ import annotations

from typing import Any

from renus.db.query.ast import (
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
                fn_name = agg.function.upper()
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
            if loading == "joined" or (rel.is_embedded and rel.target in (dict, list)):
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
                if include is None and not (
                    getattr(rel.loading, "value", rel.loading) == "joined"
                    or (rel.is_embedded and rel.target in (dict, list))
                ):
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

                if rel.is_embedded:
                    embedded_table = self.dialect.quote(
                        f"{meta.table}_{'_'.join(child_path)}"
                    )
                    join = (
                        f"LEFT JOIN {embedded_table} AS {self.dialect.quote(alias)} "
                        f"ON {self.dialect.quote(alias)}.{self.dialect.quote('parent_id')} = {owner_pk_ref}"
                    )
                else:
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
                    "raw_kind": (
                        "dict" if rel.target is dict else "list" if rel.target is list else None
                    ),
                    "embedded": bool(rel.is_embedded),
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
                        "parent_id" if rel.is_embedded else target_meta.primary_key_field,
                    )

        add(ast.source, self.dialect.quote("r0"), (), "", meta.primary_key_field)
        return result

    def _path(self, p: Path) -> str:
        if len(p.parts) == 1:
            meta = getattr(p.model, "__db_metadata__", None)
            col = p.parts[0]
            if meta:
                fmeta = meta.fields.get(col)
                if fmeta:
                    col = fmeta.column_name
            quoted = self.dialect.quote(col)
            if self._root_ref and p.model is self._root_model:
                return f"{self.dialect.quote(self._root_ref)}.{quoted}"
            return quoted

        meta = getattr(p.model, "__db_metadata__", None)
        if meta:
            rel_name = p.parts[0]
            rel = meta.relationships.get(rel_name)
            if rel and rel.is_embedded:

                parent_table = self.dialect.quote(meta.table)
                parent_pk = self.dialect.quote(meta.primary_key_field)
                embedded_table = self.dialect.quote(
                    f"{meta.table}_{'_'.join(p.parts[:-1])}"
                )
                target_field = self.dialect.quote(p.parts[-1])
                parent_fk = self.dialect.quote("parent_id")
                return (
                    f"(SELECT e.{target_field} FROM {embedded_table} e "
                    f"WHERE e.{parent_fk} = {parent_table}.{parent_pk})"
                )

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

        if isinstance(c, Logical):
            if c.operator == Operator.NOT:
                s, p = self._condition(c.children[0], table_ref=table_ref, model=model)
                return f"NOT ({s})", p

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

        if c.path is not None and op not in (
            Operator.AND,
            Operator.OR,
            Operator.NOT,
        ):
            raw_cond = self._raw_dict_condition(c, op, table_ref=table_ref)
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
            vals = (
                list(val)
                if isinstance(val, (list, tuple, set))
                else ([] if val is None else [val])
            )
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
            return self._path(path)
        col = self.dialect.quote(self._field_name(path.model, path.parts[0]))
        return f"{table_ref}.{col}" if table_ref else col

    def _is_reference_path(self, path: Path) -> bool:
        if len(path.parts) < 2:
            return False
        meta = getattr(path.model, "__db_metadata__", None)
        return bool(meta and path.parts[0] in meta.relationships and not meta.relationships[path.parts[0]].is_embedded)

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

    def _relation_any_condition(self, c: RelationAny, *, table_ref: str | None) -> tuple[str, list[Any]]:
        embedded = self._embedded_relation_any(c, table_ref=table_ref)
        if embedded is not None:
            return embedded

        relation = c.relation
        owner_model = relation.model
        owner_meta = owner_model.__db_metadata__
        owner_ref = table_ref or self.dialect.quote(owner_meta.table)
        rel_name = relation.parts[0]
        alias = self._new_alias("r")
        from_sql, joins, target_model = self._relationship_join(owner_model, rel_name, owner_ref, alias)
        sub_sql, params = self._condition(c.condition, table_ref=alias, model=target_model)
        return f"EXISTS (SELECT 1 FROM {from_sql} WHERE {' AND '.join([*joins, sub_sql])})", params

    def _embedded_relation_any(
        self,
        c: RelationAny,
        *,
        table_ref: str | None,
    ) -> tuple[str, list[Any]] | None:
        """Compile a nested ``any()`` chain over normalized embedded tables."""
        owner_model = c.relation.model
        owner_meta = getattr(owner_model, "__db_metadata__", None)
        if owner_meta is None or not c.relation.parts:
            return None

        relation_names: list[str] = []
        current_model = owner_model
        current = c
        while isinstance(current, RelationAny):
            relation_name = current.relation.parts[0]
            current_meta = getattr(current_model, "__db_metadata__", None)
            rel = current_meta.relationships.get(relation_name) if current_meta else None
            if rel is None or not rel.is_embedded:
                return None
            relation_names.append(relation_name)
            target = rel.target if isinstance(rel.target, type) else None
            if target is None:
                return None
            current_model = target
            if not isinstance(current.condition, RelationAny):
                terminal = current.condition
                break
            current = current.condition
        else:
            return None

        root_ref = table_ref or self.dialect.quote(owner_meta.table)
        table_name = self.dialect.quote(
            f"{owner_meta.table}_{'_'.join(relation_names)}"
        )
        parent_pk = self.dialect.quote(owner_meta.primary_key_field)
        terminal_sql, params = self._condition(terminal, table_ref="e", model=current_model)
        return (
            f"EXISTS (SELECT 1 FROM {table_name} e WHERE "
            f"e.{self.dialect.quote('parent_id')} = {root_ref}.{parent_pk} "
            f"AND {terminal_sql})",
            params,
        )

    def _raw_dict_condition(
        self,
        c: Condition,
        op: Operator,
        *,
        table_ref: str | None = None,
    ) -> tuple[str, list[Any]] | None:
        if c.path is None:
            return None
        paths = c.path.parts
        meta = getattr(c.path.model, "__db_metadata__", None)
        if meta is None:
            return None
        rel = meta.relationships.get(paths[0])
        if rel is None or not rel.is_embedded:
            return None

        parent_table = table_ref or self.dialect.quote(meta.table)
        parent_pk = self.dialect.quote(
            self._field_name(c.path.model, meta.primary_key_field)
        )
        parent_key = f"{parent_table}.{parent_pk}"
        e_table = self.dialect.quote(
            f"{meta.table}_{'_'.join(paths[:-1])}"
        )
        pid = self.dialect.quote("parent_id")
        rest = paths[1:]

        if rel.target is dict:
            if not rest:
                return None
            key_col = self.dialect.quote("key")
            fixed_key = (f"e.{key_col} = {self.dialect.placeholder}", [rest[0]])
            return self._embed_sub_exists(
                e_table,
                pid,
                parent_key,
                self.dialect.quote("value"),
                op,
                c.value,
                fixed_key=fixed_key,
                string_values=True,
            )

        if rel.target is list:
            return self._embed_sub_exists(
                e_table,
                pid,
                parent_key,
                self.dialect.quote("value"),
                op,
                c.value,
                string_values=True,
            )

        child_meta = getattr(rel.target, "__db_metadata__", None) \
            if isinstance(rel.target, type) else None
        for relation_name in rest[:-1]:
            if child_meta is None:
                return None
            nested_rel = child_meta.relationships.get(relation_name)
            if nested_rel is None or not nested_rel.is_embedded:
                return None
            child_meta = getattr(nested_rel.target, "__db_metadata__", None) \
                if isinstance(nested_rel.target, type) else None
        if child_meta is None:
            return None
        col_name = rest[-1] if rest else ""
        fmeta = child_meta.fields.get(col_name)
        col = self.dialect.quote(fmeta.column_name if fmeta else col_name)
        return self._embed_sub_exists(
            e_table, pid, parent_key, col, op, c.value,
        )

    def _embed_sub_exists(
        self,
        e_table: str,
        pid: str,
        parent_key: str,
        col: str,
        op: Operator,
        value: Any,
        *,
        fixed_key: tuple[str, list[Any]] | None = None,
        string_values: bool = False,
    ) -> tuple[str, list[Any]] | None:
        def enc(v: Any) -> Any:
            return str(v) if string_values else v

        if op == Operator.IS_NULL:
            inner = f"e.{pid} = {parent_key}"
            params: list[Any] = []
            if fixed_key:
                inner += f" AND {fixed_key[0]}"
                params.extend(fixed_key[1])
            inner += f" AND e.{col} IS NOT NULL"
            return f"NOT EXISTS (SELECT 1 FROM {e_table} e WHERE {inner})", params

        if op == Operator.IS_NOT_NULL:
            inner = f"e.{pid} = {parent_key}"
            params = []
            if fixed_key:
                inner += f" AND {fixed_key[0]}"
                params.extend(fixed_key[1])
            inner += f" AND e.{col} IS NOT NULL"
            return f"EXISTS (SELECT 1 FROM {e_table} e WHERE {inner})", params

        if op == Operator.EQ and value is None:
            return self._embed_sub_exists(
                e_table,
                pid,
                parent_key,
                col,
                Operator.IS_NULL,
                None,
                fixed_key=fixed_key,
                string_values=string_values,
            )

        if op == Operator.NE and value is None:
            return self._embed_sub_exists(
                e_table,
                pid,
                parent_key,
                col,
                Operator.IS_NOT_NULL,
                None,
                fixed_key=fixed_key,
                string_values=string_values,
            )

        if op == Operator.NE:
            inner = f"e.{pid} = {parent_key}"
            params: list[Any] = []
            if fixed_key:
                inner += f" AND {fixed_key[0]}"
                params.extend(fixed_key[1])
            inner += f" AND e.{col} = {self.dialect.placeholder}"
            params.append(enc(value))
            return f"NOT EXISTS (SELECT 1 FROM {e_table} e WHERE {inner})", params

        if op == Operator.EQ and isinstance(value, list) and string_values:
            clauses: list[str] = []
            params: list[Any] = []
            for v in value:
                clauses.append(
                    f"EXISTS (SELECT 1 FROM {e_table} e WHERE e.{pid} = "
                    f"{parent_key} AND e.{col} = "
                    f"{self.dialect.placeholder})"
                )
                params.append(enc(v))
            return f"( { ' AND '.join(clauses) } )", params

        if op in (Operator.IN, Operator.NOT_IN):
            vals = (
                list(value)
                if isinstance(value, (list, tuple, set))
                else ([] if value is None else [value])
            )
            if not vals:
                return ("1=0" if op == Operator.IN else "1=1"), []
            placeholders = self.dialect.placeholders(len(vals))
            expr = f"e.{col} IN ({placeholders})"
            if op == Operator.NOT_IN:
                inner = f"e.{pid} = {parent_key}"
                params: list[Any] = []
                if fixed_key:
                    inner += f" AND {fixed_key[0]}"
                    params.extend(fixed_key[1])
                params.extend(enc(v) for v in vals)
                return f"NOT EXISTS (SELECT 1 FROM {e_table} e WHERE {inner} AND {expr})", params
        else:
            op_str = {
                Operator.EQ: "=",
                Operator.NE: "<>",
                Operator.GT: ">",
                Operator.GE: ">=",
                Operator.LT: "<",
                Operator.LE: "<=",
                Operator.LIKE: "LIKE",
                Operator.REGEX: "REGEXP",
            }.get(op)
            if op == Operator.BETWEEN:
                try:
                    lower, upper = value
                except (TypeError, ValueError):
                    raise ValueError("BETWEEN requires a lower and upper value") from None
                expr = (
                    f"e.{col} BETWEEN {self.dialect.placeholder} "
                    f"AND {self.dialect.placeholder}"
                )
                vals = [lower, upper]
            elif op_str is not None:
                expr = f"e.{col} {op_str} {self.dialect.placeholder}"
                vals = [value]
            else:
                return None

        inner = f"e.{pid} = {parent_key}"
        params = []
        if fixed_key:
            inner += f" AND {fixed_key[0]}"
            params.extend(fixed_key[1])
        params.extend(enc(v) for v in vals)
        return f"EXISTS (SELECT 1 FROM {e_table} e WHERE {inner} AND {expr})", params

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
