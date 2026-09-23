from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from renus.db.core.adapter import AsyncDatabaseAdapter, MutationResult
from renus.db.core.exceptions import ValidationError
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
    Include,
    Path,
    QueryAST,
)
from renus.db.query.builder import Count, Query
from renus.db.repository.normalize import normalize_values, validate_update_values
from renus.db.repository.relationships import RelationshipCoordinator
from renus.db.transaction.core import Transaction


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

    @classmethod
    def _build_insert_ast_for_model(cls, model_cls: type, obj: Any) -> Insert:
        meta = getattr(model_cls, "__db_metadata__", None)
        values: dict[str, Any] = {}

        if meta:
            for fname, fmeta in meta.fields.items():
                if fmeta.generated and getattr(obj, fname, None) is None:
                    continue
                if hasattr(obj, fname):
                    val = (
                        obj.get_sensitive(fname)
                        if hasattr(obj, "get_sensitive")
                        else getattr(obj, fname)
                    )
                    if val is not None or fmeta.nullable:
                        values[fname] = val
        else:
            values = {
                k: v for k, v in obj.__dict__.items() if not k.startswith("_")
            }
        return Insert(source=model_cls, values=normalize_values(values))

    @classmethod
    def _build_update_ast_for_model(cls, model_cls: type, obj: Any) -> Update:
        changes: dict[str, Any] = {}
        meta = getattr(model_cls, "__db_metadata__", None)
        if hasattr(obj, "dirty_fields"):
            for fname in obj.dirty_fields():
                fmeta = meta.fields.get(fname) if meta else None
                changes[fname] = (
                    obj.get_sensitive(fname)
                    if hasattr(obj, "get_sensitive")
                    else getattr(obj, fname)
                )
        else:
            changes = {
                k: v for k, v in obj.__dict__.items() if not k.startswith("_")
            }

        filters: list[Condition] = []
        if hasattr(obj, "identity_dict"):
            for pk_name, pk_val in obj.identity_dict().items():
                filters.append(Path(model_cls, (pk_name,)) == pk_val)

        return Update(source=model_cls, 
            values=validate_update_values(model_cls,changes),
            filters=tuple(filters))

    @classmethod
    def _build_delete_ast_for_model(cls, model_cls: type, obj: Any) -> Delete:
        filters: list[Condition] = []
        if hasattr(obj, "identity_dict"):
            for pk_name, pk_val in obj.identity_dict().items():
                filters.append(Path(model_cls, (pk_name,)) == pk_val)

        return Delete(source=model_cls, filters=tuple(filters))

    def build_insert_ast(self, obj: T) -> Insert:
        """Build an insert AST from a model instance's values."""
        return self._build_insert_ast_for_model(self.model, obj)

    def build_insert_many_ast(self, objs: Iterable[T]) -> InsertMany:
        """Build a multi-row insert AST from model instances."""
        inst_list = list(objs)
        if not inst_list:
            raise ValueError("build_insert_many_ast requires at least one model instance")
        records = [self._build_insert_ast_for_model(self.model, m).values for m in inst_list]
        return InsertMany(source=self.model, records=records)

    def build_update_ast(self, obj: T) -> Update:
        """Build an update AST from a model instance's dirty fields."""
        return self._build_update_ast_for_model(self.model, obj)

    def build_delete_ast(self, obj: T) -> Delete:
        """Build a delete AST from a model instance's identity."""
        return self._build_delete_ast_for_model(self.model, obj)

    async def create(self, obj: T) -> T:
        """Insert a single model and return it with generated keys."""
        async with self._atomic(self._rel_coordinator.requires_transaction(obj)):
            insert_ast = self.build_insert_ast(obj)
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

        needs_transaction = any(
            self._rel_coordinator.requires_transaction(obj) for obj in obj_list
        )
        async with self._atomic(needs_transaction):
            insert_many_ast = self.build_insert_many_ast(obj_list)
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

            if res.generated:
                for field_name, generated_values in res.generated.items():
                    if field_name == "ids" or not isinstance(generated_values, list):
                        continue
                    for obj, generated_value in zip(obj_list, generated_values):
                        if getattr(obj, field_name, None) is None:
                            object.__setattr__(obj, field_name, generated_value)

            for obj in obj_list:
                if hasattr(obj, "_mark_persisted"):
                    getattr(obj, "_mark_persisted")()

            for obj in obj_list:
                await self._rel_coordinator.persist_relationships(obj)
            return obj_list

    async def save(self, obj: T) -> T:
        """Insert or update the model depending on its persistence state."""
        if obj.is_new():
            return await self.create(obj)

        if obj.is_persisted() and not obj.is_dirty():
            return obj

        async with self._atomic(self._rel_coordinator.requires_transaction(obj)):
            await self._rel_coordinator.cascade_on_update(obj)
            update_ast = self.build_update_ast(obj)
            if update_ast.values:
                if (
                    getattr(self.model, "__db_metadata__", None)
                    and getattr(self.model.__db_metadata__, "timestamps", False)
                    and "updated_at" in update_ast.values
                ):
                    object.__setattr__(obj, "updated_at", update_ast.values["updated_at"])
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
            values=validate_update_values(self.model, values),
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
            values=validate_update_values(self.model, values),
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
                        for pk_name, pk_val in obj.identity_dict().items():
                            pk_filters.append(Path(self.model, (pk_name,)) == pk_val)

                    update_ast = Update(source=self.model, values=soft_vals, filters=tuple(pk_filters))
                    res = await self._execute_mutation(update_ast)
                    return res.rows_affected

                del_ast = self.build_delete_ast(obj)
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

    async def restore(
        self,
        target_or_condition: T | Condition,
        *conditions: Condition,
    ) -> int:
        """Restore matching soft-deleted rows and return rows affected."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta or not meta.soft_delete:
            raise ValueError(
                f"Model '{self.model.__name__}' does not have soft_delete enabled"
            )

        if isinstance(target_or_condition, self.model):
            obj: Any = target_or_condition
            row_conditions: list[Condition] = []
            if hasattr(obj, "identity_dict"):
                for pk_name, pk_val in obj.identity_dict().items():
                    row_conditions.append(Path(self.model, (pk_name,)) == pk_val)
        else:
            row_conditions = [target_or_condition, *conditions]

        row_conditions.append(
            Path(self.model, (meta.deleted_at_field or "deleted_at",)).is_not_null()
        )
        values: dict[str, Any] = {
            "deleted_at": None,
            "is_deleted": False,
        }
        if meta.timestamps:
            values["updated_at"] = datetime.now(timezone.utc)

        update_ast = Update(
            source=self.model,
            values=values,
            filters=tuple(row_conditions),
        )
        result = await self._execute_mutation(update_ast)

        if isinstance(target_or_condition, self.model) and result.rows_affected:
            if hasattr(obj, "restore"):
                obj.restore()
            if meta.timestamps and "updated_at" in values:
                object.__setattr__(obj, "updated_at", values["updated_at"])
            if hasattr(obj, "_mark_persisted"):
                obj._mark_persisted()
        return result.rows_affected

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
                del_ast = self.build_delete_ast(obj)
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


    async def count(self, *conditions: Condition) -> int:
        """Return the number of rows matching the given conditions."""
        return await self.query(*conditions).count()

    async def exists(self, *conditions: Condition) -> bool:
        """Return whether any row matches the given conditions."""
        return await self.query(*conditions).exists()

    async def _query(self, ast: QueryAST) -> list[Any]:
        """Execute the complete AST in the adapter."""
        rows = await self.adapter.execute_query(ast)

        if ast.projection or ast.aggregates:
            result_dicts: list[dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, dict):
                    raise ValidationError(f"Adapter response must be in dict format, got {type(r).__name__}")
                result_dicts.append(dict(r))
            return result_dicts

        meta = getattr(self.model, "__db_metadata__", None)
        rel_names = set(meta.relationships.keys()) if meta else set()
        included_paths = {include.path.parts for include in ast.includes}
        objects: list[T] = []
        for r in rows:
            if isinstance(r, self.model):
                obj = r
            else:
                if not isinstance(r, dict):
                    raise ValidationError(
                        f"Adapter response must be in dict format, got {type(r).__name__}"
                    )

                data = dict(r)
                if rel_names:
                    included_relationships = {
                        path[0] for path in included_paths if path
                    }
                    for rname, relationship in meta.relationships.items():
                        if (
                            getattr(relationship, "is_embedded", False)
                            and getattr(relationship, "target", None) not in (dict, list)
                            and getattr(relationship.loading, "value", relationship.loading)
                            == "lazy"
                            and rname not in included_relationships
                            and getattr(self.adapter, "nested_documents", False)
                        ):
                            data.pop(rname, None)
                    for rname in rel_names:
                        if rname not in data:
                            rel = meta.relationships[rname]
                            if getattr(rel, "target", None) is dict:
                                data[rname] = {}
                            elif getattr(rel, "is_collection", False):
                                data[rname] = []
                            else:
                                data[rname] = None
                model_cls: Any = self.model
                obj = model_cls(data)

            if hasattr(obj, "_mark_persisted"):
                getattr(obj, "_mark_persisted")()
            objects.append(obj)

        includes = list(ast.includes)
        for include in self._includes_for_joined_relationships():
            if include.path.parts not in included_paths:
                includes.append(include)
                included_paths.add(include.path.parts)

        if includes:
            await self._rel_coordinator.load_includes(objects, tuple(includes))
        return objects

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
            or (
                getattr(relationship, "is_embedded", False)
                and getattr(relationship, "target", None) in (dict, list)
            )
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

        result = await self.adapter.execute_mutation(ast)

        if plugins is not None:
            await plugins.dispatch_after_mutation(ast, result, context)
        return result
