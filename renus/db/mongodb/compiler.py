from __future__ import annotations

import re
from typing import Any

from renus.config import Config
from renus.db.mutation.ast import (
    Delete,
    DeleteMany,
    Insert,
    InsertMany,
    MutationAST,
    Update,
    UpdateMany,
)
from renus.db.query.ast import (
    Condition,
    HavingCondition,
    Logical,
    Operator,
    Path,
    QueryAST,
    RelationAny,
)
from renus.db.relationships import RelationshipKind
from renus.datastructures.id import ID
from renus.db.mongodb.dialect import MongoDialect
from renus.util import to_plural_lower


class MongoCompiledQuery:

    __slots__ = (
        "collection",
        "filter",
        "limit",
        "meta",
        "pipeline",
        "joined",
        "projection",
        "skip",
        "sort",
    )

    def __init__(
        self,
        collection: str,
        filter_doc: dict[str, Any],
        projection: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        skip: int | None = None,
        limit: int | None = None,
        pipeline: list[dict[str, Any]] | None = None,
        meta: Any = None,
        joined: tuple[str, ...] = (),
    ) -> None:
        """Store the compiled MongoDB query attributes.

        Parameters
        ----------
        collection:
            Target collection name.
        filter_doc:
            MongoDB filter document.
        projection:
            Optional field projection document.
        sort:
            Optional list of ``(field, direction)`` sort pairs.
        skip:
            Number of documents to skip. Defaults to None.
        limit:
            Maximum number of documents to return. Defaults to None.
        pipeline:
            Optional aggregation pipeline. Defaults to None.
        """
        self.collection = collection
        self.filter = filter_doc
        self.projection = projection
        self.sort = sort or []
        self.skip = skip
        self.limit = limit
        self.pipeline = pipeline
        self.meta = meta
        self.joined = joined

class MongoCompiler:

    def __init__(self, dialect: MongoDialect | None = None) -> None:
        """Initialize the compiler with a MongoDB dialect.

        Parameters
        ----------
        dialect:
            Dialect describing BSON type support and value encoding. Defaults
            to a shared :class:`MongoDialect` instance.
        """
        self.dialect = dialect or MongoDialect()

    def compile_query(self, ast: QueryAST) -> MongoCompiledQuery:
        """Compile a query AST into a MongoCompiledQuery."""
        source = ast.source
        meta = getattr(source, "__db_metadata__", None)
        collection_name = (
            meta.table
            if meta
            else getattr(source, "table", None)
            or to_plural_lower(source.__name__)
        )

        filter_parts: list[dict[str, Any]] = []
        relation_any_lookups: dict[int, str] = {}
        relation_any_stages: list[dict[str, Any]] = []

        if meta and meta.soft_delete:
            del_field = meta.deleted_at_field or "deleted_at"
            if ast.only_deleted:
                filter_parts.append({del_field: {"$ne": None}})
            elif not ast.with_deleted:
                filter_parts.append({del_field: None})

        for cond in ast.filters:
            for relation_filter in self._relation_any_nodes(cond):
                if id(relation_filter) in relation_any_lookups:
                    continue
                relation_name = relation_filter.relation.parts[0]
                relation_meta = meta.relationships.get(relation_name) if meta else None
                target_cls = relation_meta.target if relation_meta else None
                target_meta = getattr(target_cls, "__db_metadata__", None)
                if relation_meta is None or target_meta is None:
                    raise NotImplementedError(
                        "RelationAny requires a mapped relationship target"
                    )

                if relation_meta.is_embedded:
                    continue
                lookup_name = f"__renus_relation_any_{len(relation_any_lookups)}"
                relation_any_lookups[id(relation_filter)] = lookup_name

                def mongo_field(model_meta: Any, field_name: str) -> str:
                    return "_id" if field_name == model_meta.primary_key_field else field_name

                relation_kind = getattr(relation_meta.kind, "value", relation_meta.kind)
                if relation_kind == "many_to_many":
                    if not relation_meta.through:
                        raise ValueError("ManyToMany relation requires a through table")
                    link_name = f"__renus_relation_links_{len(relation_any_lookups)}"
                    local_col = relation_meta.local_key or f"{to_plural_lower(meta.table)}_id"
                    foreign_col = relation_meta.foreign_key or f"{to_plural_lower(target_meta.table)}_id"
                    relation_any_stages.append({"$lookup": {
                        "from": relation_meta.through,
                        "localField": mongo_field(meta, meta.primary_key_field),
                        "foreignField": local_col,
                        "as": link_name,
                    }})
                    relation_any_stages.append({"$lookup": {
                        "from": target_meta.table,
                        "localField": f"{link_name}.{foreign_col}",
                        "foreignField": mongo_field(target_meta, target_meta.primary_key_field),
                        "as": lookup_name,
                    }})
                elif relation_kind == "many_to_one":
                    local_field = relation_meta.foreign_key or f"{relation_name}_id"
                    relation_any_stages.append({"$lookup": {
                        "from": target_meta.table,
                        "localField": mongo_field(meta, local_field),
                        "foreignField": mongo_field(target_meta, target_meta.primary_key_field),
                        "as": lookup_name,
                    }})
                else:
                    local_field = relation_meta.local_key or meta.primary_key_field
                    foreign_field = relation_meta.foreign_key or f"{meta.table}_id"
                    relation_any_stages.append({"$lookup": {
                        "from": target_meta.table,
                        "localField": mongo_field(meta, local_field),
                        "foreignField": foreign_field,
                        "as": lookup_name,
                    }})
            filter_parts.append(self._compile_condition(cond, relation_any_lookups))

        if ast.cursor is not None:
            cursor_path = ast.cursor_field
            if cursor_path is None and meta and meta.primary_key_field:
                cursor_path = Path(source, (meta.primary_key_field,))
            if cursor_path is not None:
                filter_parts.append({
                    self._path_str(cursor_path): {
                        "$gt": self.dialect.encode_value(ast.cursor)
                    }
                })

        filter_doc = self._combine_filter_parts(filter_parts)
        joined_stages, joined_names = self._joined_lookups_recursive(ast)

        if ast.aggregates:
            pipeline: list[dict[str, Any]] = [*relation_any_stages]
            if filter_doc:
                pipeline.append({"$match": filter_doc})

            group_id: Any
            if ast.group_by:
                group_id = {self._path_str(p): f"${self._path_str(p)}" for p in ast.group_by}
                if len(group_id) == 1:
                    group_id = list(group_id.values())[0]
            else:
                group_id = None

            group_stage: dict[str, Any] = {"_id": group_id}
            distinct_aliases: dict[str, tuple[str, str]] = {}
            for agg in ast.aggregates:
                field_target = f"${self._path_str(agg.path)}" if agg.path else 1
                if agg.distinct and agg.path:
                    temp = f"__renus_distinct_{agg.alias}"
                    distinct_aliases[agg.alias] = (temp, agg.function)
                    group_stage[temp] = {"$addToSet": field_target}
                elif agg.function == "count":
                    group_stage[agg.alias] = {"$sum": 1}
                elif agg.function == "sum":
                    group_stage[agg.alias] = {"$sum": field_target}
                elif agg.function == "avg":
                    group_stage[agg.alias] = {"$avg": field_target}
                elif agg.function == "min":
                    group_stage[agg.alias] = {"$min": field_target}
                elif agg.function == "max":
                    group_stage[agg.alias] = {"$max": field_target}
                else:
                    group_stage[agg.alias] = {"$sum": 1}

            pipeline.append({"$group": group_stage})

            project: dict[str, Any] = {"_id": 0}
            if ast.group_by:
                group_paths = [self._path_str(p) for p in ast.group_by]
                for gp in group_paths:
                    project[gp] = "$_id" if len(group_paths) == 1 else f"$_id.{gp}"
            for agg in ast.aggregates:
                if agg.alias in distinct_aliases:
                    temp, function = distinct_aliases[agg.alias]
                    if function == "count":
                        project[agg.alias] = {"$size": f"${temp}"}
                    elif function == "sum":
                        project[agg.alias] = {"$sum": f"${temp}"}
                    elif function == "avg":
                        project[agg.alias] = {"$avg": f"${temp}"}
                    else:
                        project[agg.alias] = 1
                else:
                    project[agg.alias] = 1
            pipeline.append({"$project": project})

            if ast.having:
                having_doc = self._compile_having(ast.having, ast.aggregates)
                if having_doc:
                    pipeline.append({"$match": having_doc})
            if ast.ordering:
                pipeline.append({"$sort": {
                    self._path_str(o.path): -1 if o.descending else 1
                    for o in ast.ordering
                }})
            if ast.offset is not None:
                pipeline.append({"$skip": ast.offset})
            if ast.limit is not None:
                pipeline.append({"$limit": ast.limit})

            return MongoCompiledQuery(
                collection=collection_name,
                filter_doc={},
                pipeline=pipeline,
                meta=meta,
            )

        projection_doc: dict[str, Any] | None = None
        if relation_any_stages or joined_stages:
            pipeline: list[dict[str, Any]] = [*relation_any_stages, *joined_stages]
            if filter_doc:
                pipeline.append({"$match": filter_doc})
            if ast.ordering:
                pipeline.append({"$sort": {
                    self._path_str(o.path): -1 if o.descending else 1
                    for o in ast.ordering
                }})
            if ast.offset is not None:
                pipeline.append({"$skip": ast.offset})
            if ast.limit is not None:
                pipeline.append({"$limit": ast.limit})
            if ast.projection:
                pipeline.append({"$project": {
                    "_id": 0,
                    **{self._path_str(path): 1 for path in ast.projection.paths},
                }})
            return MongoCompiledQuery(
                collection=collection_name,
                filter_doc={},
                pipeline=pipeline,
                meta=meta,
                joined=tuple(joined_names),
            )

        if ast.projection:
            projection_doc = {self._path_str(p): 1 for p in ast.projection.paths}
            if "_id" not in projection_doc:
                projection_doc["_id"] = 0

        sort_spec: list[tuple[str, int]] = []
        for o in ast.ordering:
            direction = -1 if o.descending else 1
            sort_spec.append((self._path_str(o.path), direction))

        if ast.projection and any(len(path.parts) > 1 for path in ast.projection.paths):
            pipeline: list[dict[str, Any]] = []
            if filter_doc:
                pipeline.append({"$match": filter_doc})
            if sort_spec:
                pipeline.append({"$sort": dict(sort_spec)})
            if ast.offset is not None:
                pipeline.append({"$skip": ast.offset})
            if ast.limit is not None:
                pipeline.append({"$limit": ast.limit})
            pipeline.append({"$project": {
                "_id": 0,
                **{
                    path.parts[-1]: f"${self._path_str(path)}"
                    for path in ast.projection.paths
                },
            }})
            return MongoCompiledQuery(
                collection=collection_name,
                filter_doc={},
                pipeline=pipeline,
                meta=meta,
            )

        if ast.distinct and ast.projection:
            group_id = {
                self._path_str(path): f"${self._path_str(path)}"
                for path in ast.projection.paths
            }
            pipeline: list[dict[str, Any]] = []
            if filter_doc:
                pipeline.append({"$match": filter_doc})
            pipeline.append({"$group": {"_id": group_id}})
            pipeline.append({"$project": {
                "_id": 0,
                **{
                    self._path_str(path): f"$_id.{self._path_str(path)}"
                    for path in ast.projection.paths
                },
            }})
            if sort_spec:
                pipeline.append({"$sort": {
                    self._path_str(o.path): -1 if o.descending else 1
                    for o in ast.ordering
                }})
            if ast.offset is not None:
                pipeline.append({"$skip": ast.offset})
            if ast.limit is not None:
                pipeline.append({"$limit": ast.limit})
            return MongoCompiledQuery(
                collection=collection_name,
                filter_doc={},
                pipeline=pipeline,
                meta=meta,
            )

        return MongoCompiledQuery(
            collection=collection_name,
            filter_doc=filter_doc,
            projection=projection_doc,
            sort=sort_spec,
            skip=ast.offset,
            limit=ast.limit,
            meta=meta,
            joined=tuple(joined_names),
        )

    def _joined_lookups(self, ast: QueryAST) -> tuple[list[dict[str, Any]], list[str]]:
        """Compile automatic and explicit relationship includes into one pipeline."""
        if ast.projection or ast.aggregates:
            return [], []
        root_meta = getattr(ast.source, "__db_metadata__", None)
        if root_meta is None:
            return [], []

        requested: dict[tuple[str, ...], Any] = {
            item.path.parts: item for item in ast.includes
        }
        expanded: dict[tuple[str, ...], Any] = dict(requested)
        for item in ast.includes:
            for nested in item.nested:
                expanded[(*item.path.parts, *nested.path.parts)] = nested
        requested = expanded
        for name, rel in root_meta.relationships.items():
            loading = getattr(rel.loading, "value", rel.loading)
            if loading == "joined" or (rel.is_embedded and rel.target in (dict, list)):
                requested.setdefault((name,), None)

        stages: list[dict[str, Any]] = []
        names: list[str] = []

        def mongo_field(model_meta: Any, field_name: str) -> str:
            return "_id" if field_name == model_meta.primary_key_field else field_name

        for path, include in requested.items():
            if not path:
                continue
            name = path[0]
            rel = root_meta.relationships.get(name)
            if rel is None or rel.is_embedded:
                continue
            target = rel.target if isinstance(rel.target, type) else None
            target_meta = getattr(target, "__db_metadata__", None)
            if len(path) > 1:
                continue
            if target_meta is None:
                continue
            kind = getattr(rel.kind, "value", rel.kind)
            include_filter = getattr(include, "filter", None)
            link_name = ""
            nested_items = [
                (item_path, item)
                for item_path, item in requested.items()
                if len(item_path) > 1 and item_path[0] == name
            ]
            if kind == "many_to_many":
                if not rel.through:
                    continue
                local_col = rel.local_key or f"{to_plural_lower(root_meta.table)}_id"
                foreign_col = rel.foreign_key or f"{to_plural_lower(target_meta.table)}_id"
                link_name = f"__renus_joined_links_{name}"
                stages.append({"$lookup": {
                    "from": str(rel.through),
                    "localField": mongo_field(root_meta, root_meta.primary_key_field),
                    "foreignField": local_col,
                    "as": link_name,
                }})
                stages.append({"$lookup": {
                    "from": target_meta.table,
                    "let": {"ids": f"${link_name}.{foreign_col}"},
                    "pipeline": [
                        {"$match": {"$expr": {"$in": [
                            f"${mongo_field(target_meta, target_meta.primary_key_field)}",
                            "$$ids",
                        ]}}},
                        *([{"$match": self._compile_condition(include_filter)}] if include_filter is not None else []),
                    ],
                    "as": name,
                }})
            else:
                if kind == "many_to_one":
                    local_field = rel.foreign_key or f"{name}_id"
                    foreign_field = mongo_field(target_meta, target_meta.primary_key_field)
                else:
                    local_field = rel.local_key or root_meta.primary_key_field
                    foreign_field = rel.foreign_key or f"{to_plural_lower(root_meta.table)}_id"

                if nested_items:
                    nested_pipeline: list[dict[str, Any]] = [
                        {"$match": {"$expr": {"$eq": [
                            f"${foreign_field}", "$$local"
                        ]}}}
                    ]
                    if include_filter is not None:
                        nested_pipeline.append({"$match": self._compile_condition(include_filter)})
                    for nested_path, nested_item in nested_items:
                        nested_name = nested_path[1]
                        nested_rel = target_meta.relationships.get(nested_name)
                        nested_target = getattr(nested_rel, "target", None) if nested_rel else None
                        nested_meta = getattr(nested_target, "__db_metadata__", None)
                        if nested_rel is None or nested_meta is None or nested_rel.is_embedded:
                            continue

                        nested_local = nested_rel.foreign_key or f"{nested_name}_id"
                        nested_foreign = mongo_field(nested_meta, nested_meta.primary_key_field)
                        nested_pipeline.append({"$lookup": {
                            "from": nested_meta.table,
                            "localField": nested_local,
                            "foreignField": nested_foreign,
                            "as": nested_name,
                        }})
                    stages.append({"$lookup": {
                        "from": target_meta.table,
                        "let": {"local": f"${mongo_field(root_meta, local_field)}"},
                        "pipeline": nested_pipeline,
                        "as": name,
                    }})
                elif include_filter is None:
                    stages.append({"$lookup": {
                        "from": target_meta.table,
                        "localField": mongo_field(root_meta, local_field),
                        "foreignField": foreign_field,
                        "as": name,
                    }})
                else:
                    stages.append({"$lookup": {
                        "from": target_meta.table,
                        "let": {"local": f"${mongo_field(root_meta, local_field)}"},
                        "pipeline": [
                            {"$match": {"$expr": {"$eq": [
                                f"${foreign_field}", "$$local"
                            ]}}},
                            {"$match": self._compile_condition(include_filter)},
                        ],
                        "as": name,
                    }})
            if kind == "many_to_many" and link_name:
                stages.append({"$unset": link_name})
            names.append(name)

        return stages, names

    def _joined_lookups_recursive(
        self,
        ast: QueryAST,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Build recursive relationship lookups in one aggregation pipeline."""
        if ast.projection or ast.aggregates:
            return [], []
        root_meta = getattr(ast.source, "__db_metadata__", None)
        if root_meta is None:
            return [], []

        requested: dict[tuple[str, ...], Any] = {}

        def collect(item: Any, prefix: tuple[str, ...] = ()) -> None:
            path = (*prefix, *item.path.parts)
            requested[path] = item
            for nested in item.nested:
                collect(nested, path)

        for item in ast.includes:
            collect(item)

        def mongo_field(model_meta: Any, field_name: str) -> str:
            return "_id" if field_name == model_meta.primary_key_field else field_name

        def build(owner_meta: Any, prefix: tuple[str, ...]) -> list[dict[str, Any]]:
            direct: dict[str, Any] = {}
            for path, include in requested.items():
                if len(path) <= len(prefix) or path[: len(prefix)] != prefix:
                    continue
                remainder = path[len(prefix) :]
                if remainder:
                    direct.setdefault(remainder[0], include)
            for name, rel in owner_meta.relationships.items():
                loading = getattr(rel.loading, "value", rel.loading)
                if loading == "joined" or (rel.is_embedded and rel.target in (dict, list)):
                    direct.setdefault(name, None)

            stages: list[dict[str, Any]] = []
            for name, include in direct.items():
                rel = owner_meta.relationships.get(name)
                if rel is None or rel.is_embedded:
                    continue
                target = rel.target if isinstance(rel.target, type) else None
                target_meta = getattr(target, "__db_metadata__", None)
                if target_meta is None:
                    continue
                child_prefix = (*prefix, name)
                child_stages = build(target_meta, child_prefix)
                include_filter = getattr(include, "filter", None)
                kind = getattr(rel.kind, "value", rel.kind)

                if kind == "many_to_many":
                    if not rel.through:
                        continue
                    local_col = rel.local_key or f"{to_plural_lower(owner_meta.table)}_id"
                    foreign_col = rel.foreign_key or f"{to_plural_lower(target_meta.table)}_id"
                    link_name = f"__renus_lookup_links_{'_'.join(child_prefix)}"
                    stages.append({"$lookup": {
                        "from": str(rel.through),
                        "localField": mongo_field(owner_meta, owner_meta.primary_key_field),
                        "foreignField": local_col,
                        "as": link_name,
                    }})
                    target_pipeline: list[dict[str, Any]] = [{"$match": {"$expr": {"$in": [
                        f"${mongo_field(target_meta, target_meta.primary_key_field)}",
                        f"${link_name}.{foreign_col}",
                    ]}}}]
                    if include_filter is not None:
                        target_pipeline.append({"$match": self._compile_condition(include_filter)})
                    target_pipeline.extend(child_stages)
                    stages.append({"$lookup": {
                        "from": target_meta.table,
                        "let": {"ids": f"${link_name}.{foreign_col}"},
                        "pipeline": [
                            {"$match": {"$expr": {"$in": [
                                f"${mongo_field(target_meta, target_meta.primary_key_field)}",
                                "$$ids",
                            ]}}},
                            *([{"$match": self._compile_condition(include_filter)}] if include_filter is not None else []),
                            *child_stages,
                        ],
                        "as": name,
                    }})
                    stages.append({"$unset": link_name})
                    continue

                if kind == "many_to_one":
                    local_field = rel.foreign_key or f"{name}_id"
                    foreign_field = mongo_field(target_meta, target_meta.primary_key_field)
                else:
                    local_field = rel.local_key or owner_meta.primary_key_field
                    foreign_field = rel.foreign_key or f"{to_plural_lower(owner_meta.table)}_id"

                if include_filter is None and not child_stages:
                    stages.append({"$lookup": {
                        "from": target_meta.table,
                        "localField": mongo_field(owner_meta, local_field),
                        "foreignField": foreign_field,
                        "as": name,
                    }})
                else:
                    pipeline: list[dict[str, Any]] = [{"$match": {"$expr": {"$eq": [
                        f"${foreign_field}", "$$local"
                    ]}}}]
                    if include_filter is not None:
                        pipeline.append({"$match": self._compile_condition(include_filter)})
                    pipeline.extend(child_stages)
                    stages.append({"$lookup": {
                        "from": target_meta.table,
                        "let": {"local": f"${mongo_field(owner_meta, local_field)}"},
                        "pipeline": pipeline,
                        "as": name,
                    }})
            return stages

        return build(root_meta, ()), [
            name for name, rel in root_meta.relationships.items()
            if getattr(rel.loading, "value", rel.loading) == "joined"
            or any(path == (name,) for path in requested)
        ]

    def _path_str(self, p: Path) -> str:
        parts = list(p.parts)

        meta = getattr(p.model, "__db_metadata__", None)
        if meta and meta.primary_key_field == "id" and parts == ["id"]:
            return "_id"
        return ".".join(parts)

    def _compile_having(self, conditions: tuple[Any, ...], aggregates: tuple[Any, ...]) -> dict[str, Any]:
        clauses = [self._compile_having_condition(condition, aggregates) for condition in conditions]
        clauses = [clause for clause in clauses if clause]
        if not clauses:
            return {}
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def _compile_having_condition(self, condition: Any, aggregates: tuple[Any, ...]) -> dict[str, Any]:
        if not isinstance(condition, HavingCondition):
            return {}
        if condition.operator in (Operator.AND, Operator.OR):
            children = condition.aggregate
            if not isinstance(children, tuple):
                return {}
            clauses = [self._compile_having_condition(child, aggregates) for child in children]
            clauses = [clause for clause in clauses if clause]
            if not clauses:
                return {}
            if condition.operator == Operator.OR:
                return {"$or": clauses}
            return {"$and": clauses}

        aggregate = condition.aggregate
        alias = next(
            (
                item.alias
                for item in aggregates
                if item.function == aggregate.function
                and item.path == aggregate.path
                and item.distinct == aggregate.distinct
            ),
            None,
        )
        operator = {
            Operator.EQ: "$eq",
            Operator.NE: "$ne",
            Operator.GT: "$gt",
            Operator.GE: "$gte",
            Operator.LT: "$lt",
            Operator.LE: "$lte",
        }.get(condition.operator)
        if alias is None or operator is None:
            return {}
        return {alias: {operator: condition.value}}

    def _is_raw_list_path(self, c: Condition) -> bool:
        p = c.path
        if p is None or not p.parts:
            return False
        meta = getattr(p.model, "__db_metadata__", None)
        if not meta:
            return False
        rel = meta.relationships.get(p.parts[0])
        return (
            rel is not None
            and rel.kind == RelationshipKind.EMBEDDED_MANY
            and rel.target is list
        )

    def _relation_any_nodes(self, c: Condition) -> tuple[RelationAny, ...]:
        if isinstance(c, RelationAny):
            return (c,)
        if isinstance(c, Logical):
            return tuple(
                relation_filter
                for child in c.children
                for relation_filter in self._relation_any_nodes(child)
            )
        return ()

    def _compile_condition(
        self,
        c: Condition,
        relation_any_lookups: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        if isinstance(c, RelationAny):
            if relation_any_lookups and id(c) in relation_any_lookups:
                return {
                    relation_any_lookups[id(c)]: {
                        "$elemMatch": self._compile_condition(
                            c.condition, relation_any_lookups
                        )
                    }
                }
            relation_meta = getattr(c.relation.model, "__db_metadata__", None)
            relation = (
                relation_meta.relationships.get(c.relation.parts[0])
                if relation_meta and c.relation.parts
                else None
            )
            if relation is not None and relation.is_embedded:
                return self._compile_embedded_any(c, relation_any_lookups)
            rel_path = self._path_str(c.relation)
            sub_filter = self._compile_condition(c.condition, relation_any_lookups)
            return {rel_path: {"$elemMatch": sub_filter}}

        if isinstance(c, Logical):
            if c.operator == Operator.NOT:
                return {
                    "$nor": [
                        self._compile_condition(c.children[0], relation_any_lookups)
                    ]
                }
            op_str = "$and" if c.operator == Operator.AND else "$or"
            return {
                op_str: [
                    self._compile_condition(child, relation_any_lookups)
                    for child in c.children
                ]
            }

        path = self._path_str(c.path) if c.path else ""
        op = c.operator
        val = c.value

        if self._is_raw_list_path(c):
            if op == Operator.EQ and isinstance(val, list):
                return {path: {"$all": val}}
            if op == Operator.IN and not isinstance(val, (list, tuple, set)):
                return {path: val}

        if op == Operator.EQ:
            return {path: self.dialect.encode_value(val)}
        if op == Operator.NE:
            return {path: {"$ne": self.dialect.encode_value(val)}}
        if op == Operator.GT:
            return {path: {"$gt": self.dialect.encode_value(val)}}
        if op == Operator.GE:
            return {path: {"$gte": self.dialect.encode_value(val)}}
        if op == Operator.LT:
            return {path: {"$lt": self.dialect.encode_value(val)}}
        if op == Operator.LE:
            return {path: {"$lte": self.dialect.encode_value(val)}}
        if op == Operator.IN:
            if not isinstance(val, (list, tuple, set)):
                return {path: self.dialect.encode_value(val)}
            return {path: {"$in": [self.dialect.encode_value(v) for v in val]}}
        if op == Operator.NOT_IN:
            return {path: {"$nin": [self.dialect.encode_value(v) for v in val]}}
        if op == Operator.IS_NULL:
            return {path: None}
        if op == Operator.IS_NOT_NULL:
            return {path: {"$ne": None}}
        if op == Operator.LIKE:
            raw_str = str(val)
            pattern = ""
            for ch in raw_str:
                if ch == "%":
                    pattern += ".*"
                elif ch == "_":
                    pattern += "."
                else:
                    pattern += re.escape(ch)
            return {path: {"$regex": f"^{pattern}$"}}
        if op == Operator.REGEX:
            return {path: {"$regex": str(val)}}
        if op == Operator.BETWEEN:
            lower, upper = val
            return {
                path: {
                    "$gte": self.dialect.encode_value(lower),
                    "$lte": self.dialect.encode_value(upper),
                }
            }
        raise ValueError(f"Unsupported MongoDB query operator: {op}")

    def _prefix_mongo_condition(self, doc: dict[str, Any], prefix: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in doc.items():
            if key.startswith("$"):
                if isinstance(value, list):
                    result[key] = [
                        self._prefix_mongo_condition(item, prefix)
                        if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    result[key] = value
            else:
                result[f"{prefix}.{key}"] = value
        return result

    def _compile_embedded_any(
        self,
        c: RelationAny,
        relation_any_lookups: dict[int, str] | None,
    ) -> dict[str, Any]:
        relation_meta = getattr(c.relation.model, "__db_metadata__", None)
        relation_name = c.relation.parts[0]
        relation = relation_meta.relationships[relation_name]
        if isinstance(c.condition, RelationAny):
            nested = self._compile_embedded_any(c.condition, relation_any_lookups)
        else:
            nested = self._compile_condition(c.condition, relation_any_lookups)
        if relation.is_collection:
            return {relation_name: {"$elemMatch": nested}}
        return self._prefix_mongo_condition(nested, relation_name)

    def compile_mutation(self, m: MutationAST) -> tuple[str, str, dict[str, Any], Any]:
        """Compile a mutation AST into a collection, operation, and arguments."""
        source = m.source
        meta = getattr(source, "__db_metadata__", None)
        auto_inc_field = self._auto_inc_field(meta)
        collection = (
            meta.table
            if meta
            else getattr(source, "table", None)
            or to_plural_lower(source.__name__)
        )

        if isinstance(m, Insert):
            doc = self._map_doc_for_mongo(m.values, meta)
            self._needs_auto_int_id(meta, m.values)
            return collection, "insert_one", doc, {
                "auto_inc_field": auto_inc_field,
                "meta": meta,
            }

        if isinstance(m, InsertMany):
            docs = [self._map_doc_for_mongo(r, meta) for r in m.records]
            for record in m.records:
                self._needs_auto_int_id(meta, record)
            return collection, "insert_many", {"docs": docs}, {
                "auto_inc_field": auto_inc_field,
                "meta": meta,
            }

        if isinstance(m, Update):
            filt = self._compile_filters(m.filters, meta)
            updates = {"$set": self._map_doc_for_mongo(m.values, meta)}
            return collection, "update_one", filt, updates

        if isinstance(m, UpdateMany):
            filt = self._compile_filters(m.filters, meta)
            updates = {"$set": self._map_doc_for_mongo(m.values, meta)}
            return collection, "update_many", filt, updates

        if isinstance(m, Delete):
            filt = self._compile_filters(m.filters, meta)
            return collection, "delete_one", filt, None

        if isinstance(m, DeleteMany):
            filt = self._compile_filters(m.filters, meta)
            return collection, "delete_many", filt, None


        raise NotImplementedError(f"Unsupported mutation: {type(m).__name__}")

    def _auto_inc_field(self, meta: Any) -> str | None:
        """Validate and return the model's configured auto-increment field."""
        if not meta:
            return None

        configured_id = Config("database").get("ID", int)
        auto_inc_fields: list[str] = []
        for field_name, field_meta in meta.fields.items():
            if not field_meta.database.auto_inc:
                continue
            if configured_id is not int:
                raise ValueError("MongoDB auto_inc requires Config('database').ID=int")
            if field_meta.inferred_type not in (int, ID):
                raise ValueError(
                    f"MongoDB auto_inc field '{field_name}' must have type int or ID"
                )
            auto_inc_fields.append(field_name)

        if len(auto_inc_fields) > 1:
            raise ValueError("MongoDB supports one auto_inc field per model")
        return auto_inc_fields[0] if auto_inc_fields else None

    def _needs_auto_int_id(self, meta: Any, values: dict[str, Any]) -> bool:
        """Return whether an auto-increment integer is needed for an insert."""
        auto_inc_field = self._auto_inc_field(meta)
        return auto_inc_field is not None and auto_inc_field not in values

    def _map_doc_for_mongo(
        self,
        doc: dict[str, Any],
        meta: Any,
    ) -> dict[str, Any]:
        mapped: dict[str, Any] = {}
        for k, v in doc.items():
            if k == "id" and (not meta or meta.primary_key_field == "id") and "_id" not in doc:
                mapped["_id"] = self.dialect.encode_value(v)
            else:
                mapped[k] = self.dialect.encode_value(v)
        return mapped

    def _combine_filter_parts(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        if not parts:
            return {}
        if len(parts) == 1:
            return parts[0]

        can_flatten = True
        merged: dict[str, Any] = {}
        for p in parts:
            for k, v in p.items():
                if k in merged or k in ("$or", "$nor"):
                    can_flatten = False
                    break
                merged[k] = v
            if not can_flatten:
                break

        if can_flatten:
            return merged
        return {"$and": parts}

    def _compile_filters(
        self,
        filters: tuple[Condition, ...],
        meta: Any,
    ) -> dict[str, Any]:
        parts: list[dict[str, Any]] = []
        for c in filters:
            parts.append(self._compile_condition(c))

        return self._combine_filter_parts(parts)
