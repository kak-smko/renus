from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Generic, TypeVar
from uuid import UUID

from renus.db.core.adapter import AsyncDatabaseAdapter, MutationResult
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
from renus.db.query.ast import Condition, Path, QueryAST
from renus.db.query.builder import Count, Query
from renus.db.serialization.core import from_dict
from renus.db.transaction.core import Transaction

__all__ = ["Repository"]

T = TypeVar("T")

class Repository(Generic[T]):

    def __init__(
        self,
        adapter_or_database: AsyncDatabaseAdapter | Any,
        model: type[T],
        connection_name: str = "primary",
    ) -> None:
        """Resolve the backend adapter and prepare the repository.

        Parameters
        ----------
        adapter_or_database:
            An ``AsyncDatabaseAdapter`` instance, or a database object from
            which the active adapter is derived.
        model:
            The model class this repository operates on.
        connection_name:
            Name of the connection to select from a database object.
            Defaults to ``"primary"``.
        """
        self.model: type[T] = model
        self.connection_name: str = connection_name

        if isinstance(adapter_or_database, AsyncDatabaseAdapter):
            self._adapter: AsyncDatabaseAdapter = adapter_or_database
            self._db: Any = None
        else:
            self._db = adapter_or_database
            if hasattr(adapter_or_database, "adapter"):
                self._adapter = adapter_or_database.adapter(connection_name)
            elif hasattr(adapter_or_database, "_adapter"):
                self._adapter = adapter_or_database._adapter
            else:
                self._adapter = adapter_or_database

        from renus.db.repository.relationships import RelationshipCoordinator

        self._rel_coordinator = RelationshipCoordinator(self)

    @property
    def adapter(self) -> AsyncDatabaseAdapter:
        """Return the active database adapter."""
        return self._adapter

    @asynccontextmanager
    async def _atomic(self) -> AsyncIterator[None]:
        if self.adapter._in_active_transaction():
            yield
            return
        async with Transaction(self.adapter):
            yield

    def query(self, *conditions: Condition) -> Query[T]:
        """Start a new query, optionally filtered by the given conditions."""
        q = Query(self)
        if conditions:
            return q.where(*conditions)
        return q

    async def create(self, obj: T) -> T:
        """Insert a single model and return it with generated keys."""
        async with self._atomic():
            insert_ast = Insert.from_model(obj)
            result = await self._execute_mutation(insert_ast)

            meta = getattr(self.model, "__db_metadata__", None)
            if meta and result.last_id is not None:
                pk_field = meta.primary_key_field
                if getattr(obj, pk_field, None) is None:
                    object.__setattr__(obj, pk_field, result.last_id)

            if result.generated:
                for k, v in result.generated.items():
                    if getattr(obj, k, None) is None:
                        object.__setattr__(obj, k, v)

            if hasattr(obj, "_mark_persisted"):
                getattr(obj, "_mark_persisted")()

            await self._rel_coordinator.persist_relationships(obj)
        return obj

    async def create_many(self, objs: Iterable[T]) -> list[T]:
        """Insert multiple models in bulk and return them."""
        obj_list = list(objs)
        if not obj_list:
            return []

        async with self._atomic():
            insert_many_ast = InsertMany.from_models(obj_list)
            res = await self._execute_mutation(insert_many_ast)
            meta = getattr(self.model, "__db_metadata__", None)
            if meta:
                pk_field = meta.primary_key_field
                if res.generated and "ids" in res.generated:
                    for obj, gen_id in zip(obj_list, res.generated["ids"]):
                        if getattr(obj, pk_field, None) is None:
                            object.__setattr__(obj, pk_field, gen_id)
                elif res.last_id is not None and len(obj_list) > 0:
                    first_id = res.last_id - len(obj_list) + 1
                    for idx, obj in enumerate(obj_list):
                        if getattr(obj, pk_field, None) is None:
                            object.__setattr__(obj, pk_field, first_id + idx)

            for obj in obj_list:
                if hasattr(obj, "_mark_persisted"):
                    getattr(obj, "_mark_persisted")()

            for obj in obj_list:
                await self._rel_coordinator.persist_relationships(obj)
            return obj_list

    async def save(self, obj: T) -> T:
        """Insert or update the model depending on its persistence state."""
        if getattr(obj, "is_new", False):
            return await self.create(obj)

        if getattr(obj, "is_persisted", False) and not getattr(obj, "is_dirty", True):
            return obj

        async with self._atomic():
            update_ast = Update.from_model(obj)
            if update_ast.values:
                await self._execute_mutation(update_ast)

            if hasattr(obj, "_mark_persisted"):
                getattr(obj, "_mark_persisted")()

            await self._rel_coordinator.persist_relationships(obj)
        return obj

    async def update(
        self,
        *conditions: Condition,
        values: dict[Any, Any] | None = None,
    ) -> int:
        """Update matching rows with the given values and return rows affected."""
        if values is None:
            if not conditions:
                raise ValueError("update requires filter conditions and values")

            last_arg = conditions[-1]
            if isinstance(last_arg, dict):
                values = last_arg
                conditions = conditions[:-1]
            else:
                raise ValueError("update requires a dictionary of values")

        update_ast = Update(
            source=self.model,
            values=values,
            filters=conditions,
        )
        result = await self._execute_mutation(update_ast)
        return result.rows_affected

    async def update_many(
        self,
        *conditions: Condition,
        values: dict[Any, Any] | None = None,
        limit: int | None = None,
    ) -> int:
        """Bulk-update matching rows (up to a limit) and return rows affected."""
        if values is None:
            if not conditions:
                raise ValueError("update_many requires filter conditions and values")
            last_arg = conditions[-1]
            if isinstance(last_arg, dict):
                values = last_arg
                conditions = conditions[:-1]
            else:
                raise ValueError("update_many requires a dictionary of values")

        update_many_ast = UpdateMany(
            source=self.model,
            values=values,
            filters=conditions,
            limit=limit,
        )
        result = await self._execute_mutation(update_many_ast)
        return result.rows_affected

    async def delete(
        self,
        target_or_condition: T | Condition,
        *conditions: Condition,
    ) -> int:
        """Delete a single model or matching rows, honoring soft deletes."""
        meta = getattr(self.model, "__db_metadata__", None)

        if isinstance(target_or_condition, self.model):
            obj: Any = target_or_condition

            async with self._atomic():
                await self._rel_coordinator.cascade_delete(obj)
                if meta and meta.soft_delete:

                    if hasattr(obj, "soft_delete"):
                        obj.soft_delete()
                    now = datetime.now(timezone.utc)
                    soft_vals = {
                        "deleted_at": now,
                        "is_deleted": True,
                    }
                    if meta.timestamps:
                        soft_vals["updated_at"] = now

                    pk_filters: list[Condition] = []
                    if hasattr(obj, "identity_dict"):
                        for pk_name, pk_val in obj.identity_dict.items():
                            pk_filters.append(Path(self.model, (pk_name,)) == pk_val)

                    update_ast = Update(source=self.model, values=soft_vals, filters=tuple(pk_filters))
                    res = await self._execute_mutation(update_ast)
                    return res.rows_affected

                del_ast = Delete.from_model(obj)
                res = await self._execute_mutation(del_ast)
                if hasattr(obj, "_mark_deleted"):
                    obj._mark_deleted()
                return res.rows_affected

        first_cond: Condition = target_or_condition
        all_conditions: tuple[Condition, ...] = (first_cond,) + conditions
        if meta and meta.soft_delete:
            now = datetime.now(timezone.utc)
            soft_vals = {"deleted_at": now, "is_deleted": True}
            if meta.timestamps:
                soft_vals["updated_at"] = now
            update_ast = Update(source=self.model, values=soft_vals, filters=all_conditions)
            res = await self._execute_mutation(update_ast)
            return res.rows_affected

        del_ast = Delete(source=self.model, filters=all_conditions)
        res = await self._execute_mutation(del_ast)
        return res.rows_affected

    async def delete_many(
        self,
        *conditions: Condition,
        limit: int | None = None,
    ) -> int:
        """Bulk-delete matching rows (up to a limit) and return rows affected."""
        meta = getattr(self.model, "__db_metadata__", None)

        if meta and meta.soft_delete:
            now = datetime.now(timezone.utc)
            soft_vals = {"deleted_at": now, "is_deleted": True}
            if meta.timestamps:
                soft_vals["updated_at"] = now
            update_many_ast = UpdateMany(
                source=self.model,
                values=soft_vals,
                filters=conditions,
                limit=limit,
            )
            res = await self._execute_mutation(update_many_ast)
            return res.rows_affected

        async with self._atomic():
            await self._rel_coordinator.cascade_delete_many(*conditions, limit=limit)

            del_many_ast = DeleteMany(
                source=self.model,
                filters=conditions,
                limit=limit,
            )
            res = await self._execute_mutation(del_many_ast)
            return res.rows_affected

    async def delete_many_ast(self, ast: QueryAST) -> int:
        """Delete rows matching the filters described by the given AST."""
        return await self.delete_many(*ast.filters, limit=ast.limit)

    async def upsert(
        self,
        conflict_target: Iterable[Path | str] | None = None,
        create_values: dict[Any, Any] | None = None,
        update_values: dict[Any, Any] | None = None,
        target: T | None = None,
    ) -> int:
        """Insert or update a row on conflict for the target and return rows affected."""
        if target is not None:
            upsert_ast = Upsert.from_model(target, conflict_target=conflict_target)
        elif isinstance(conflict_target, self.model):
            upsert_ast = Upsert.from_model(conflict_target)
        else:
            if conflict_target is None or create_values is None or update_values is None:
                raise ValueError("upsert requires conflict_target, create_values, and update_values")
            upsert_ast = Upsert(
                source=self.model,
                conflict_target=conflict_target,
                create_values=create_values,
                update_values=update_values,
            )

        res = await self._execute_mutation(upsert_ast)
        return res.rows_affected

    async def count(self, *conditions: Condition) -> int:
        """Return the number of rows matching the given conditions."""
        return await self.query(*conditions).count()

    async def exists(self, *conditions: Condition) -> bool:
        """Return whether any row matches the given conditions."""
        return await self.query(*conditions).exists()

    async def _query(self, ast: QueryAST) -> list[Any]:
        compile_fn = getattr(self.adapter, "compile_query", None)
        compiled = compile_fn(ast) if compile_fn is not None else ast
        rows = await self.adapter.execute_query(compiled)

        if ast.projection or ast.aggregates:
            return [dict(r) if not isinstance(r, dict) else r for r in rows]

        objects = [self._hydrate(r) for r in rows]
        if ast.includes:
            await self._rel_coordinator.load_includes(objects, ast.includes)
        return objects

    async def _count(self, ast: QueryAST) -> int:
        count_ast = replace(
            ast,
            aggregates=(Count().as_("count"),),
            projection=None,
            ordering=(),
            offset=None,
            limit=None,
        )
        rows = await self._query(count_ast)
        if rows:
            r = rows[0]
            if isinstance(r, dict):
                return int(r.get("count", 0))
            if isinstance(r, (int, float)):
                return int(r)
        return 0

    async def _exists(self, ast: QueryAST) -> bool:
        exists_ast = replace(ast, limit=1, offset=None, ordering=(), projection=None)
        rows = await self._query(exists_ast)
        return len(rows) > 0

    async def _execute_mutation(self, ast: MutationAST) -> MutationResult:
        plugins = self._db.plugins if self._db is not None else None
        context: dict[str, Any] = {}
        if plugins is not None:
            await plugins.dispatch_before_mutation(ast, context)

        compile_fn = getattr(self.adapter, "compile_mutation", None)
        compiled = compile_fn(ast) if compile_fn is not None else ast
        result = await self.adapter.execute_mutation(compiled)

        if plugins is not None:
            await plugins.dispatch_after_mutation(ast, result, context)
        return result

    def _coerce_row_for_model(self, row: dict[str, Any]) -> dict[str, Any]:
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return row

        data = dict(row)
        for fname, fmeta in meta.fields.items():
            col = fmeta.column_name
            if col in data:
                val = data[col]
            elif fname in data:
                val = data[fname]
            else:
                continue

            if val is None:
                data[fname] = None
                continue

            target_type = fmeta.inferred_type
            type_str = str(target_type).lower()

            if (target_type is bool or type_str in ("bool", "boolean")) and isinstance(val, int):
                data[fname] = bool(val)
                continue

            if (target_type is datetime or "datetime" in type_str) and isinstance(val, str):
                try:
                    data[fname] = datetime.fromisoformat(val.rstrip("Z"))
                except Exception:
                    pass
                continue

            if (target_type is date or type_str == "date") and isinstance(val, str):
                try:
                    data[fname] = date.fromisoformat(val)
                except Exception:
                    pass
                continue

            if (target_type is UUID or "uuid" in type_str) and isinstance(val, str):
                try:
                    data[fname] = UUID(val)
                except Exception:
                    pass
                continue

            if (target_type is Decimal or "decimal" in type_str) and isinstance(val, (str, int, float)):
                try:
                    data[fname] = Decimal(str(val))
                except Exception:
                    pass
                continue

            if (
                target_type in (dict, list)
                or getattr(target_type, "__origin__", None) in (dict, list)
                or type_str.startswith("dict")
                or type_str.startswith("list")
            ) and isinstance(val, str):
                try:
                    data[fname] = json.loads(val)
                except Exception:
                    pass
                continue

            data[fname] = val

        rel_meta = getattr(meta, "relationships", None)
        if rel_meta:
            for rname, rmeta in rel_meta.items():
                if not rmeta.is_embedded or rname not in data:
                    continue
                rval = data[rname]
                target = rmeta.target if isinstance(rmeta.target, type) else None
                if target is None or rval is None:
                    continue
                if rmeta.is_collection:
                    if isinstance(rval, list):
                        data[rname] = [
                            from_dict(target, item, validate=False) if isinstance(item, dict) else item
                            for item in rval
                        ]
                elif isinstance(rval, dict):
                    data[rname] = from_dict(target, rval, validate=False)

        return data

    def _hydrate(self, row: Any) -> T:
        if isinstance(row, self.model):
            obj: Any = row
        else:
            coerced = self._coerce_row_for_model(dict(row))
            model_cls: Any = self.model
            obj = model_cls(coerced)

        if hasattr(obj, "_mark_persisted"):
            getattr(obj, "_mark_persisted")()

        return obj
