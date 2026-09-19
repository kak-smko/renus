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
    Upsert,
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
from renus.db.models.id import ID
from renus.db.mongodb.dialect import MongoDialect
from renus.util import to_plural_lower

__all__ = ["MongoCompiledQuery", "MongoCompiler"]

class MongoCompiledQuery:

    __slots__ = (
        "collection",
        "filter",
        "limit",
        "pipeline",
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

        if meta and meta.soft_delete:
            del_field = meta.deleted_at_field or "deleted_at"
            if ast.only_deleted:
                filter_parts.append({del_field: {"$ne": None}})
            elif not ast.with_deleted:
                filter_parts.append({del_field: None})

        for cond in ast.filters:
            filter_parts.append(self._compile_condition(cond))

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

        if ast.aggregates:
            pipeline: list[dict[str, Any]] = []
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
            distinct_aliases: dict[str, str] = {}
            for agg in ast.aggregates:
                field_target = f"${self._path_str(agg.path)}" if agg.path else 1
                if agg.function == "count" and agg.distinct and agg.path:
                    temp = f"__renus_distinct_{agg.alias}"
                    distinct_aliases[agg.alias] = temp
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
                    project[agg.alias] = {"$size": f"${distinct_aliases[agg.alias]}"}
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
            )

        projection_doc: dict[str, Any] | None = None
        if ast.projection:
            projection_doc = {self._path_str(p): 1 for p in ast.projection.paths}
            if "_id" not in projection_doc:
                projection_doc["_id"] = 0

        sort_spec: list[tuple[str, int]] = []
        for o in ast.ordering:
            direction = -1 if o.descending else 1
            sort_spec.append((self._path_str(o.path), direction))

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
            )

        return MongoCompiledQuery(
            collection=collection_name,
            filter_doc=filter_doc,
            projection=projection_doc,
            sort=sort_spec,
            skip=ast.offset,
            limit=ast.limit,
        )

    def _path_str(self, p: Path) -> str:
        parts = list(p.parts)

        meta = getattr(p.model, "__db_metadata__", None)
        if meta and meta.primary_key_field == "id" and parts == ["id"]:
            return "_id"
        return ".".join(parts)

    def _compile_having(self, conditions: tuple[Any, ...], aggregates: tuple[Any, ...]) -> dict[str, Any]:
        clauses: list[dict[str, Any]] = []
        for condition in conditions:
            if not isinstance(condition, HavingCondition):
                continue
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
            if alias is None:
                continue
            operator = {
                Operator.EQ: "$eq",
                Operator.NE: "$ne",
                Operator.GT: "$gt",
                Operator.GE: "$gte",
                Operator.LT: "$lt",
                Operator.LE: "$lte",
            }.get(condition.operator)
            if operator:
                clauses.append({alias: {operator: condition.value}})
        if not clauses:
            return {}
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

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

    def _compile_condition(self, c: Condition) -> dict[str, Any]:
        if isinstance(c, RelationAny):

            rel_path = self._path_str(c.relation)
            sub_filter = self._compile_condition(c.condition)
            return {rel_path: {"$elemMatch": sub_filter}}

        if isinstance(c, Logical):
            if c.operator == Operator.NOT:
                return {"$nor": [self._compile_condition(c.children[0])]}
            op_str = "$and" if c.operator == Operator.AND else "$or"
            return {op_str: [self._compile_condition(child) for child in c.children]}

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
            }

        if isinstance(m, InsertMany):
            docs = [self._map_doc_for_mongo(r, meta) for r in m.records]
            for record in m.records:
                self._needs_auto_int_id(meta, record)
            return collection, "insert_many", {"docs": docs}, {
                "auto_inc_field": auto_inc_field,
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

        if isinstance(m, Upsert):
            conflict_keys = list(m.conflict_target)
            filt = {k: m.create_values.get(k) for k in conflict_keys}
            set_values = self._map_doc_for_mongo(m.update_values, meta)
            # MongoDB's immutable _id may be supplied for the insert branch,
            # but must never appear in the update document.
            set_values.pop("_id", None)
            create_values = self._map_doc_for_mongo(m.create_values, meta)
            update_doc: dict[str, Any] = {}
            if set_values:
                update_doc["$set"] = set_values
            if create_values:
                # MongoDB forbids a path in both ``$set`` and ``$setOnInsert``.
                # On conflict, update_values win; the remaining create fields
                # are applied atomically only on the insert branch.
                insert_only = {
                    k: v for k, v in create_values.items() if k not in set_values
                }
                if insert_only:
                    update_doc["$setOnInsert"] = insert_only
            return collection, "upsert", filt, update_doc

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
