from __future__ import annotations

import re
from typing import Any

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
    Logical,
    Operator,
    Path,
    QueryAST,
    RelationAny,
)
from renus.db.relationships import RelationshipKind

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

    def compile_query(self, ast: QueryAST) -> MongoCompiledQuery:
        """Compile a query AST into a MongoCompiledQuery."""
        source = ast.source
        meta = getattr(source, "__db_metadata__", None)
        collection_name = meta.table if meta else source.__name__.lower() + "s"

        filter_parts: list[dict[str, Any]] = []

        if meta and meta.soft_delete:
            del_field = meta.deleted_at_field or "deleted_at"
            if ast.only_deleted:
                filter_parts.append({del_field: {"$ne": None}})
            elif not ast.with_deleted:
                filter_parts.append({del_field: None})

        for cond in ast.filters:
            filter_parts.append(self._compile_condition(cond))

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
            for agg in ast.aggregates:
                field_target = f"${self._path_str(agg.path)}" if agg.path else 1
                if agg.function == "count":
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

            if ast.group_by:
                group_paths = [self._path_str(p) for p in ast.group_by]
                project: dict[str, Any] = {}
                for gp in group_paths:
                    if len(ast.group_by) == 1:
                        project[gp] = "$_id"
                    else:
                        project[gp] = f"$_id.{gp}"
                for agg in ast.aggregates:
                    project[agg.alias] = 1
                pipeline.append({"$project": project})

            return MongoCompiledQuery(
                collection=collection_name,
                filter_doc={},
                pipeline=pipeline,
            )

        projection_doc: dict[str, Any] | None = None
        if ast.projection:
            projection_doc = {self._path_str(p): 1 for p in ast.projection.paths}

        sort_spec: list[tuple[str, int]] = []
        for o in ast.ordering:
            direction = -1 if o.descending else 1
            sort_spec.append((self._path_str(o.path), direction))

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
            return {path: val}

        if op == Operator.NE:
            return {path: {"$ne": val}}

        if op == Operator.GT:
            return {path: {"$gt": val}}

        if op == Operator.GE:
            return {path: {"$gte": val}}

        if op == Operator.LT:
            return {path: {"$lt": val}}

        if op == Operator.LE:
            return {path: {"$lte": val}}

        if op == Operator.IN:
            return {path: {"$in": list(val)}}

        if op == Operator.NOT_IN:
            return {path: {"$nin": list(val)}}

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
            return {path: {"$gte": lower, "$lte": upper}}

        raise ValueError(f"Unsupported MongoDB query operator: {op}")

    def compile_mutation(self, m: MutationAST) -> tuple[str, str, dict[str, Any], Any]:
        """Compile a mutation AST into a collection, operation, and arguments."""
        source = m.source
        meta = getattr(source, "__db_metadata__", None)
        collection = meta.table if meta else source.__name__.lower() + "s"

        if isinstance(m, Insert):
            doc = self._map_doc_for_mongo(m.values, meta)
            return collection, "insert_one", doc, None

        if isinstance(m, InsertMany):
            docs = [self._map_doc_for_mongo(r, meta) for r in m.records]
            return collection, "insert_many", {"docs": docs}, None

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
            update_doc: dict[str, Any] = {}
            if m.update_values:
                update_doc["$set"] = self._map_doc_for_mongo(m.update_values, meta)
            if m.create_values:
                update_doc["$setOnInsert"] = self._map_doc_for_mongo(m.create_values, meta)
            return collection, "upsert", filt, update_doc

        raise NotImplementedError(f"Unsupported mutation: {type(m).__name__}")

    def _map_doc_for_mongo(
        self,
        doc: dict[str, Any],
        meta: Any,
    ) -> dict[str, Any]:
        mapped: dict[str, Any] = {}
        for k, v in doc.items():
            if k == "id" and (not meta or meta.primary_key_field == "id") and "_id" not in doc:
                mapped["_id"] = v
            else:
                mapped[k] = v
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
