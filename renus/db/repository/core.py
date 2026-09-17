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
from renus.db.query.ast import (
    Condition,
    Logical,
    Operator,
    Path,
    Include,
    QueryAST,
    RelationAny,
)
from renus.db.query.builder import Count, Query
from renus.db.repository.relationships import RelationshipCoordinator
from renus.db.serialization.core import from_dict
from renus.db.models.id import ID
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

        self._rel_coordinator = RelationshipCoordinator(self)

    @property
    def adapter(self) -> AsyncDatabaseAdapter:
        """Return the active database adapter."""
        return self._adapter

    @asynccontextmanager
    async def _atomic(self, required: bool = True) -> AsyncIterator[None]:
        if not required or self.adapter._in_active_transaction():
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

    def where(self, *conditions: Condition) -> Query[T]:
        """Start a new query, optionally filtered by the given conditions.

        Alias of :meth:`query`, provided so queries read naturally off the
        repository (e.g. ``users.where(User.name == "Ali").first()``).
        """
        return self.query(*conditions)

    async def create(self, obj: T) -> T:
        """Insert a single model and return it with generated keys."""
        async with self._atomic(self._rel_coordinator.requires_transaction(obj)):
            insert_ast = Insert.from_model(obj)
            result = await self._execute_mutation(insert_ast)

            meta = getattr(self.model, "__db_metadata__", None)
            if meta and result.last_id is not None:
                pk_field = meta.primary_key_field
                if getattr(obj, pk_field, None) is None:
                    pk_meta = meta.fields.get(pk_field)
                    generated_id = result.last_id
                    if pk_meta is not None and pk_meta.inferred_type is ID:
                        generated_id = self.adapter.decode_value(result.last_id, pk_meta)
                    object.__setattr__(obj, pk_field, generated_id)

            if result.generated:
                for k, v in result.generated.items():
                    if getattr(obj, k, None) is None:
                        field_meta = meta.fields.get(k) if meta else None
                        generated_value = v
                        if field_meta is not None and field_meta.inferred_type is ID:
                            generated_value = self.adapter.decode_value(v, field_meta)
                        object.__setattr__(obj, k, generated_value)

            if hasattr(obj, "_mark_persisted"):
                getattr(obj, "_mark_persisted")()

            await self._rel_coordinator.persist_relationships(obj)
        return obj

    async def create_many(self, objs: Iterable[T]) -> list[T]:
        """Insert multiple models in bulk and return them."""
        obj_list = list(objs)
        if not obj_list:
            return []

        needs_transaction = any(
            self._rel_coordinator.requires_transaction(obj) for obj in obj_list
        )
        async with self._atomic(needs_transaction):
            insert_many_ast = InsertMany.from_models(obj_list)
            res = await self._execute_mutation(insert_many_ast)
            meta = getattr(self.model, "__db_metadata__", None)
            if meta:
                pk_field = meta.primary_key_field
                if res.generated and "ids" in res.generated:
                    pk_meta = meta.fields.get(pk_field)
                    for obj, gen_id in zip(obj_list, res.generated["ids"]):
                        if getattr(obj, pk_field, None) is None:
                            generated_id = gen_id
                            if pk_meta is not None and pk_meta.inferred_type is ID:
                                generated_id = self.adapter.decode_value(gen_id, pk_meta)
                            object.__setattr__(obj, pk_field, generated_id)
                elif res.last_id is not None and len(obj_list) > 0:
                    first_id = res.last_id - len(obj_list) + 1
                    for idx, obj in enumerate(obj_list):
                        if getattr(obj, pk_field, None) is None:
                            object.__setattr__(obj, pk_field, first_id + idx)

            if res.generated:
                for field_name, generated_values in res.generated.items():
                    if field_name == "ids" or not isinstance(generated_values, list):
                        continue
                    field_meta = meta.fields.get(field_name) if meta else None
                    for obj, generated_value in zip(obj_list, generated_values):
                        if getattr(obj, field_name, None) is None:
                            if field_meta is not None and field_meta.inferred_type is ID:
                                generated_value = self.adapter.decode_value(
                                    generated_value, field_meta
                                )
                            object.__setattr__(obj, field_name, generated_value)

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

        async with self._atomic(self._rel_coordinator.requires_transaction(obj)):
            await self._rel_coordinator.cascade_on_update(obj)
            update_ast = Update.from_model(obj)
            if update_ast.values:
                await self._execute_mutation(update_ast)

            if hasattr(obj, "_mark_persisted"):
                getattr(obj, "_mark_persisted")()

            await self._rel_coordinator.persist_relationships(obj)
        return obj

    async def update(self,*conditions: Condition,values: dict[Any, Any] | None = None,) -> int:
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
        self,*conditions: Condition,values: dict[Any, Any] | None = None,) -> int:
        """Bulk-update matching rows and return rows affected."""
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
        )
        result = await self._execute_mutation(update_many_ast)
        return result.rows_affected

    async def delete(self,target_or_condition: T | Condition,*conditions: Condition,) -> int:
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

    async def delete_many(self,*conditions: Condition,) -> int:
        """Bulk-delete matching rows and return rows affected."""
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
            )
            res = await self._execute_mutation(update_many_ast)
            return res.rows_affected

        async with self._atomic():
            await self._rel_coordinator.cascade_delete_many(*conditions)

            del_many_ast = DeleteMany(
                source=self.model,
                filters=conditions,
            )
            res = await self._execute_mutation(del_many_ast)
            return res.rows_affected

    async def hard_delete(
        self,
        target_or_condition: T | Condition,
        *conditions: Condition,
    ) -> int:
        """Physically delete a single model or matching rows, ignoring soft deletes.
        """
        if isinstance(target_or_condition, self.model):
            obj: Any = target_or_condition
            async with self._atomic():
                await self._rel_coordinator.cascade_delete(obj, hard=True)
                del_ast = Delete.from_model(obj)
                res = await self._execute_mutation(del_ast)
                if hasattr(obj, "_mark_deleted"):
                    obj._mark_deleted()
                return res.rows_affected

        hard_conditions: tuple[Condition, ...] = (target_or_condition,) + conditions
        async with self._atomic():
            await self._rel_coordinator.cascade_delete_many(*hard_conditions, hard=True)
            del_ast = Delete(source=self.model, filters=hard_conditions)
            res = await self._execute_mutation(del_ast)
            return res.rows_affected

    async def hard_delete_many(
        self,
        *conditions: Condition,
    ) -> int:
        """Physically bulk-delete matching rows, ignoring soft deletes.

        Returns the number of rows physically removed.
        """
        async with self._atomic():
            await self._rel_coordinator.cascade_delete_many(*conditions, hard=True)
            del_many_ast = DeleteMany(
                source=self.model,
                filters=conditions,
            )
            res = await self._execute_mutation(del_many_ast)
            return res.rows_affected

    async def upsert(self, conflict_target: Iterable[Path | str] | None = None, create_values: dict[Any, Any] | None = None, update_values: dict[Any, Any] | None = None, target: T | None = None) -> int:
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

    async def _upsert_where(
        self,
        filters: tuple[Condition, ...],
        values: dict[Any, Any],
    ) -> int:
        """Perform an upsert keyed on the query's equality filters.

        Equality conditions in ``filters`` become the conflict target and are
        merged into the create values, so that ``repo.where(field == value)``
        inserted-or-updates the row matching that field. Returns rows affected.
        """
        conflict_target: list[Path | str] = []
        create_values: dict[Any, Any] = dict(values)
        update_values: dict[Any, Any] = dict(values)

        for cond in filters:
            if (
                isinstance(cond, Condition)
                and not isinstance(cond, (Logical, RelationAny))
                and cond.operator == Operator.EQ
                and cond.path is not None
                and cond.value is not None
            ):
                conflict_target.append(cond.path)
                create_values[cond.path.parts[-1]] = cond.value

        if not conflict_target:
            meta = getattr(self.model, "__db_metadata__", None)
            pk_fields = tuple(getattr(meta, "primary_key_fields", ()) or ())
            if pk_fields:
                conflict_target = list(pk_fields)
            else:
                raise ValueError(
                    "upsert requires an equality where() condition or a primary key"
                )

        upsert_ast = Upsert(
            source=self.model,
            conflict_target=conflict_target,
            create_values=create_values,
            update_values=update_values,
            filters=filters,
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
        relation_filters = self._relation_filters(ast.filters)
        backend_filters = tuple(
            cond for cond in ast.filters if cond not in relation_filters
        )
        backend_ast = replace(ast, filters=backend_filters)
        compile_fn = getattr(self.adapter, "compile_query", None)
        compiled = compile_fn(backend_ast) if compile_fn is not None else backend_ast
        rows = await self.adapter.execute_query(compiled)

        if ast.projection or ast.aggregates:
            return [dict(r) if not isinstance(r, dict) else r for r in rows]

        objects = [self._hydrate(r) for r in rows]
        includes = list(ast.includes)
        included_paths = {include.path.parts for include in includes}

        for include in self._includes_for_relation_filters(relation_filters):
            if include.path.parts not in included_paths:
                includes.append(include)
                included_paths.add(include.path.parts)

        for include in self._includes_for_joined_relationships():
            if include.path.parts not in included_paths:
                includes.append(include)
                included_paths.add(include.path.parts)

        if includes:
            await self._rel_coordinator.load_includes(objects, tuple(includes))
        if relation_filters:
            objects = [
                obj for obj in objects
                if all(self._matches_relation_filter(obj, cond) for cond in relation_filters)
            ]
        return objects

    def _relation_filters(self, filters: tuple[Condition, ...]) -> list[Condition]:
        relationships = self.model.__db_metadata__.relationships
        return [
            cond for cond in filters
            if isinstance(cond, Condition)
            and not isinstance(cond, Logical)
            and cond.path is not None
            and cond.path.parts
            and (rel := relationships.get(cond.path.parts[0])) is not None
            and (not rel.is_embedded or rel.target not in (dict, list))
        ]

    def _includes_for_relation_filters(self, filters: list[Condition]) -> list[Any]:
        includes = []
        for cond in filters:
            path = cond.path
            if path is None or not path.parts:
                continue
            include = self._include_path(self.model, path.parts)
            if include is not None:
                includes.append(include)
        return includes

    def _includes_for_joined_relationships(self) -> list[Include]:
        """Return relationships configured for automatic eager loading.

        ``joined`` is represented by the same relationship coordinator used for
        explicit includes. This keeps loading consistent across SQL and document
        adapters while making the relationship part of every normal model result.
        """
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return []

        return [
            Include(Path(self.model, (name,)))
            for name, relationship in meta.relationships.items()
            if getattr(relationship.loading, "value", relationship.loading) == "joined"
        ]

    def _include_path(self, model: type, parts: tuple[str, ...]):
        relationships = model.__db_metadata__.relationships
        if not parts or parts[0] not in relationships:
            return None
        rel_path = Path(model, (parts[0],))
        if len(parts) == 1:
            return Include(rel_path)
        target = relationships[parts[0]].target
        if not isinstance(target, type):
            return Include(rel_path)
        nested = self._include_path(target, parts[1:])
        return Include(rel_path) if nested is None else Include(rel_path, nested=(nested,))

    @staticmethod
    def _path_value(obj: Any, parts: tuple[str, ...]) -> Any:
        if not parts:
            return obj
        if isinstance(obj, list):
            values = [Repository._path_value(item, parts) for item in obj]
            return [value for item in values for value in (item if isinstance(item, list) else [item])]
        if isinstance(obj, dict):
            return Repository._path_value(obj.get(parts[0]), parts[1:])
        return Repository._path_value(getattr(obj, parts[0], None), parts[1:])

    def _matches_relation_filter(self, obj: Any, cond: Condition) -> bool:
        value = self._path_value(obj, cond.path.parts)
        values = value if isinstance(value, list) else [value]
        if cond.operator == Operator.EQ:
            return any(item == cond.value for item in values)
        if cond.operator == Operator.IN:
            return any(item in cond.value for item in values)
        if cond.operator == Operator.NE:
            return all(item != cond.value for item in values)
        if cond.operator == Operator.NOT_IN:
            return all(item not in cond.value for item in values)
        if cond.operator == Operator.GT:
            return any(item > cond.value for item in values if item is not None)
        if cond.operator == Operator.GE:
            return any(item >= cond.value for item in values if item is not None)
        if cond.operator == Operator.LT:
            return any(item < cond.value for item in values if item is not None)
        if cond.operator == Operator.LE:
            return any(item <= cond.value for item in values if item is not None)
        if cond.operator == Operator.LIKE:
            pattern = str(cond.value).replace("%", "")
            return any(pattern in str(item) for item in values if item is not None)
        if cond.operator == Operator.BETWEEN:
            lower, upper = cond.value
            return any(
                lower <= item <= upper for item in values if item is not None
            )
        raise ValueError(f"Unsupported relation filter operator: {cond.operator}")

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

        data = self.adapter.decode_row(dict(row), meta)

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
