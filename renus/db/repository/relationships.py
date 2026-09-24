from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from renus.db.core.exceptions import IntegrityError
from renus.db.mutation.ast import (
    DeleteMany,
    Insert,
    InsertMany,
    Update,
    UpdateMany,
)
from renus.db.query.ast import Condition, Include, Path, QueryAST
from renus.db.relationships import RelationshipKind
from renus.db.serialization.core import to_dict
from renus.db.transaction.core import Transaction
from renus.util import to_plural_lower


def _string_value(v: Any) -> str:
    if not isinstance(v, str):
        raise TypeError(
            f"Embedded dict/list values must be strings, got {type(v).__name__}: {v!r}"
        )
    return v

def _string_parse(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _junction_columns(owner_meta: Any, rel: Any, target_meta: Any) -> tuple[str, str]:
    """Return the (owner, target) column names of a many-to-many junction table.

    Column names come from the explicit relationship keys when given, otherwise
    they are derived from the singularised owner and target table names (e.g.
    ``employee_id`` and ``role_id`` for employees/roles).
    """
    local_col = rel.local_key or f"{to_plural_lower(owner_meta.table)}_id"
    foreign_col = rel.foreign_key or f"{to_plural_lower(target_meta.table)}_id"
    return local_col, foreign_col

def _junction_source(through_table: str) -> Any:
    """Build a synthetic source type for a raw junction ``through`` table."""
    return type(through_table, (), {"__db_metadata__": None, "table": through_table})

class RelationshipCoordinator:

    def __init__(self, repository: Any) -> None:
        """Create a coordinator bound to the given repository.

        Parameters
        ----------
        repository:
            Repository whose model relationships are persisted and loaded.
        """
        self.repo = repository

    @property
    def model(self) -> type:
        """Return the repository's model class."""
        return self.repo.model

    @property
    def adapter(self) -> Any:
        """Return the repository's database adapter."""
        return self.repo.adapter


    @asynccontextmanager
    async def _atomic(self,required: bool = True) -> AsyncIterator[None]:
        if not required or self.adapter._in_active_transaction():
            yield
            return
        async with Transaction(self.adapter):
            yield

    def requires_transaction(self, obj: Any) -> bool:
        """Return whether saving ``obj`` can write more than its main table."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return False

        is_new = bool(getattr(obj, "is_new", False))
        for rname, rel in meta.relationships.items():
            value = getattr(obj, rname, None)
            if value is None:
                continue

            if rel.kind in (
                RelationshipKind.EMBEDDED_ONE,
                RelationshipKind.EMBEDDED_MANY,
            ):
                if self.adapter.nested_documents:
                    continue
                if rel.kind == RelationshipKind.EMBEDDED_MANY and is_new and not value:
                    continue
                return True

            if rel.kind in (
                RelationshipKind.ONE_TO_MANY,
                RelationshipKind.ONE_TO_ONE,
            ) and rel.on_save == "cascade" and value:
                return True

            if rel.kind == RelationshipKind.MANY_TO_ONE and rel.on_save == "cascade":
                return True

            if rel.kind == RelationshipKind.MANY_TO_MANY and value:
                return True

        return False

    async def persist_relationships(self, obj: Any) -> None:
        """Persist all configured relationships for the given model object."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return

        parent_pk = meta.primary_key_field
        parent_id = getattr(obj, parent_pk, None)
        if parent_id is None:
            return

        for rname, rel in meta.relationships.items():
            val = getattr(obj, rname, None)
            if val is None:
                continue

            if rel.kind == RelationshipKind.EMBEDDED_ONE:
                if self.adapter.nested_documents:
                    await self._embed_one_in_document(meta, rname, obj)
                else:
                    await self._persist_embedded_one(meta, rname, rel, parent_id, val)

            elif rel.kind == RelationshipKind.EMBEDDED_MANY:
                if self.adapter.nested_documents:
                    await self._embed_many_in_document(meta, rname, obj)
                elif not (getattr(obj, "is_new", False) and not val):
                    await self._persist_embedded_many(meta, rname, rel, parent_id, val)

            elif rel.kind == RelationshipKind.ONE_TO_MANY and (
                rel.on_save == "cascade"
            ):
                await self._persist_one_to_many(meta, rel, parent_id, val)

            elif rel.kind == RelationshipKind.ONE_TO_ONE and (
                rel.on_save == "cascade"
            ):
                await self._persist_one_to_one(meta, rel, parent_id, val)

            elif rel.kind == RelationshipKind.MANY_TO_ONE and rel.on_save == "cascade":
                await self._persist_many_to_one(obj, rel)

            elif rel.kind == RelationshipKind.MANY_TO_MANY and val:
                await self._persist_many_to_many(meta, rel, parent_id, val)

    async def _persist_many_to_one(
        self,
        obj: Any,
        rel: Any,
    ) -> None:
        """Persist the referenced parent and link this model's foreign key to it.

        Used when a many-to-one relationship cascades on save: the referenced
        parent is created only when it is not already stored, then the local
        foreign key on the holder is updated to point at it.
        """
        parent = getattr(obj, rel.name, None)
        if parent is None:
            return
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        parent_meta = getattr(target_cls, "__db_metadata__", None)
        obj_meta = getattr(self.model, "__db_metadata__", None)
        fk_name = rel.foreign_key
        if parent_meta is None or obj_meta is None or not fk_name:
            return

        parent_pk = parent_meta.primary_key_field
        parent_id = getattr(parent, parent_pk, None)
        parent_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)
        exists = parent_id is not None and await parent_repo.exists(
            Path(target_cls, (parent_pk,)) == parent_id
        )
        if not exists:
            await parent_repo.save(parent)
            parent_id = getattr(parent, parent_pk, None)
        if parent_id is None:
            return

        if getattr(obj, fk_name, None) is None:
            obj_pk = obj_meta.primary_key_field
            setattr(obj, fk_name, parent_id)
            upd_ast = Update(
                source=self.model,
                values={fk_name: parent_id},
                filters=(Path(self.model, (obj_pk,)) == getattr(obj, obj_pk, None),),
            )
            await self.adapter.execute_mutation(upd_ast)

    async def _persist_many_to_many(
        self,
        parent_meta: Any,
        rel: Any,
        parent_id: Any,
        children: Iterable[Any] | None,
    ) -> None:
        """Reconcile the many-to-many junction rows for a parent record.

        The matching ``through`` table rows are replaced so the persisted links
        exactly match the given collection. Related target records are NOT
        deleted (many-to-many uses ``restrict``); only the links change.
        """
        through_table = rel.through
        if not through_table:
            return

        target_meta = self._mtm_target_meta(rel)
        if target_meta is None:
            return
        target_cls = target_meta.model

        target_pk = target_meta.primary_key_field
        local_col, foreign_col = _junction_columns(parent_meta, rel, target_meta)
        junction_source = _junction_source(through_table)

        # Clear the existing links for this parent, then re-insert the new set.
        del_ast = DeleteMany(
            source=junction_source,
            filters=(Path(junction_source, (local_col,)) == parent_id,),
        )
        await self.adapter.execute_mutation(del_ast)

        cascade = rel.on_save == "cascade"
        target_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)

        records: list[dict[str, Any]] = []
        linked_target_ids: set[Any] = set()
        for child in children or []:
            fk_val = (
                child.get(target_pk)
                if isinstance(child, dict)
                else getattr(child, target_pk, None)
            )
            already_stored = fk_val is not None and await target_repo.exists(
                Path(target_cls, (target_pk,)) == fk_val
            )
            if not already_stored:
                if cascade:
                    # Create a missing target so it has an id to link against.
                    await target_repo.save(child)
                    fk_val = (
                        child.get(target_pk)
                        if isinstance(child, dict)
                        else getattr(child, target_pk, None)
                    )
                else:
                    # No action: only link targets that are already stored.
                    continue
            if fk_val is None or fk_val in linked_target_ids:
                continue
            linked_target_ids.add(fk_val)
            records.append({local_col: parent_id, foreign_col: fk_val})

        if records:
            ins = InsertMany(source=junction_source, records=records)
            await self.adapter.execute_mutation(ins)

    @staticmethod
    def _mtm_target_meta(rel: Any) -> Any:
        """Resolve a many-to-many target's metadata, or ``None`` if unknown.
        """
        target_cls = rel.target if isinstance(rel.target, type) else None
        if target_cls is None:
            try:
                target_cls = rel.resolve_target()
            except (ValueError, KeyError):
                return None
        return getattr(target_cls, "__db_metadata__", None)

    def _rel_is_raw(self, rel_name: str) -> bool:
        rel = self.model.__db_metadata__.relationships.get(rel_name)

        return rel is not None and rel.target in (dict, list)

    async def _embed_one_in_document(self, parent_meta: Any, rel_name: str, obj: Any) -> None:
        pk = parent_meta.primary_key_field
        parent_id = getattr(obj, pk)
        child = getattr(obj, rel_name)
        if self._rel_is_raw(rel_name) and child is not None:
            for k, v in child.items():
                _string_value(k)
                _string_value(v)
            value = child
        else:
            value = to_dict(child)
        update_ast = Update(
            source=self.model,
            values={rel_name: value},
            filters=(Path(self.model, (pk,)) == parent_id,),
        )
        await self.adapter.execute_mutation(update_ast)

    async def _embed_many_in_document(self, parent_meta: Any, rel_name: str, obj: Any) -> None:
        pk = parent_meta.primary_key_field
        parent_id = getattr(obj, pk)
        items = getattr(obj, rel_name)
        if self._rel_is_raw(rel_name):
            for item in items:
                _string_value(item)
            value = list(items)
        else:
            value = [to_dict(item) for item in items]
        update_ast = Update(
            source=self.model,
            values={rel_name: value},
            filters=(Path(self.model, (pk,)) == parent_id,),
        )
        await self.adapter.execute_mutation(update_ast)

    async def _persist_embedded_one(
        self,
        parent_meta: Any,
        rel_name: str,
        rel: Any,
        parent_id: Any,
        child: Any,
        *,
        table_prefix: str | None = None,
    ) -> None:
        if rel.target is dict:
            return await self._persist_raw_embedded_one(
                parent_meta,
                rel_name,
                parent_id,
                child,
                table_prefix=table_prefix,
            )

        child_dict = child.to_dict() if hasattr(child, "to_dict") else dict(child)

        child_meta = getattr(child, "__db_metadata__", None)
        if child_meta is not None:
            child_dict = {
                fname: child_dict[fname]
                for fname in child_meta.fields
                if fname in child_dict
            }
            pk_fmeta = child_meta.fields.get(child_meta.primary_key_field)
            if pk_fmeta is not None and pk_fmeta.generated:
                child_dict.pop("id", None)

        child_dict["parent_id"] = parent_id
        table_name = (
            f"{table_prefix}_{rel_name}"
            if table_prefix is not None
            else f"{parent_meta.table}_{rel_name}"
        )

        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        async with self._atomic():
            del_ast = DeleteMany(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            ins_ast = Insert(source=embedded_source, values=child_dict)
            await self.adapter.execute_mutation(ins_ast)

        if child_meta is not None:
            for nested_name, nested_rel in child_meta.relationships.items():
                nested_value = getattr(child, nested_name, None)
                if nested_value is None:
                    continue
                if nested_rel.kind == RelationshipKind.EMBEDDED_ONE:
                    await self._persist_embedded_one(
                        child_meta,
                        nested_name,
                        nested_rel,
                        parent_id,
                        nested_value,
                        table_prefix=table_name,
                    )
                elif nested_rel.kind == RelationshipKind.EMBEDDED_MANY:
                    await self._persist_embedded_many(
                        child_meta,
                        nested_name,
                        nested_rel,
                        parent_id,
                        nested_value,
                        table_prefix=table_name,
                    )

    async def _persist_embedded_many(
        self,
        parent_meta: Any,
        rel_name: str,
        rel: Any,
        parent_id: Any,
        items: Iterable[Any],
        *,
        table_prefix: str | None = None,
    ) -> None:
        if rel.target is list:
            return await self._persist_raw_embedded_many(
                parent_meta,
                rel_name,
                parent_id,
                items,
                table_prefix=table_prefix,
            )

        table_name = (
            f"{table_prefix}_{rel_name}"
            if table_prefix is not None
            else f"{parent_meta.table}_{rel_name}"
        )
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        records: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            d = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            item_meta = getattr(item, "__db_metadata__", None)
            if item_meta is not None:
                d = {fname: d[fname] for fname in item_meta.fields if fname in d}
                pk_fmeta = item_meta.fields.get(item_meta.primary_key_field)
                if pk_fmeta is not None and pk_fmeta.generated:
                    d.pop("id", None)
            d["parent_id"] = parent_id
            records.append(d)

        required=len(records)>0
        async with self._atomic(required):
            del_ast = DeleteMany(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            if required:
                ins_many = InsertMany(source=embedded_source, records=records)
                await self.adapter.execute_mutation(ins_many)

        for item in items:
            item_meta = getattr(item, "__db_metadata__", None)
            if item_meta is None:
                continue
            for nested_name, nested_rel in item_meta.relationships.items():
                nested_value = getattr(item, nested_name, None)
                if nested_value is None:
                    continue
                if nested_rel.kind == RelationshipKind.EMBEDDED_ONE:
                    await self._persist_embedded_one(
                        item_meta,
                        nested_name,
                        nested_rel,
                        parent_id,
                        nested_value,
                        table_prefix=table_name,
                    )
                elif nested_rel.kind == RelationshipKind.EMBEDDED_MANY:
                    await self._persist_embedded_many(
                        item_meta,
                        nested_name,
                        nested_rel,
                        parent_id,
                        nested_value,
                        table_prefix=table_name,
                    )

    async def _persist_raw_embedded_one(
        self,
        parent_meta: Any,
        rel_name: str,
        parent_id: Any,
        data: dict[str, Any] | None,
        *,
        table_prefix: str | None = None,
    ) -> None:
        table_name = (
            f"{table_prefix}_{rel_name}"
            if table_prefix is not None
            else f"{parent_meta.table}_{rel_name}"
        )
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})
        required= data is not None and len(data.items())>0
        async with self._atomic(required):
            del_ast = DeleteMany(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            if required:
                records = [
                    {"parent_id": parent_id, "key": _string_value(k), "value": _string_value(v)}
                    for k, v in data.items()
                ]
                ins = InsertMany(source=embedded_source, records=records)
                await self.adapter.execute_mutation(ins)

    async def _persist_raw_embedded_many(
        self,
        parent_meta: Any,
        rel_name: str,
        parent_id: Any,
        items: Iterable[Any],
        *,
        table_prefix: str | None = None,
    ) -> None:
        table_name = (
            f"{table_prefix}_{rel_name}"
            if table_prefix is not None
            else f"{parent_meta.table}_{rel_name}"
        )
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        records = [
            {"parent_id": parent_id, "pos": idx, "value": _string_value(item)}
            for idx, item in enumerate(items)
        ]

        async with self._atomic(len(records)>0):
            del_ast = DeleteMany(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            if len(records)>0:
                ins = InsertMany(source=embedded_source, records=records)
                await self.adapter.execute_mutation(ins)

    async def _persist_one_to_one(
        self,
        parent_meta: Any,
        rel: Any,
        parent_id: Any,
        child: Any,
    ) -> None:
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)

        fk_name = rel.foreign_key or f"{to_plural_lower(parent_meta.table)}_id"
        object.__setattr__(child, fk_name, parent_id)
        await child_repo.save(child)

    async def _persist_one_to_many(
        self,
        parent_meta: Any,
        rel: Any,
        parent_id: Any,
        children: Iterable[Any],
    ) -> None:
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)

        fk_name = rel.foreign_key or f"{to_plural_lower(parent_meta.table)}_id"

        for child in children:
            object.__setattr__(child, fk_name, parent_id)
            await child_repo.save(child)

    async def cascade_delete(self, obj: Any, hard: bool = False) -> None:
        """Cascade-delete related rows for a single model object."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return

        parent_pk = meta.primary_key_field
        parent_id = getattr(obj, parent_pk, None)
        if parent_id is None:
            return

        await self._cascade_delete_for_parent_ids(meta, [parent_id], hard=hard)

    async def cascade_delete_many(
        self,
        *conditions: Condition,
        hard: bool = False,
    ) -> None:
        """Cascade-delete related rows for all rows matching the conditions."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta or not meta.relationships:
            return

        parent_pk = meta.primary_key_field
        q = self.repo.query()
        if hard:
            q = q.with_deleted()
        if conditions:
            q = q.where(*conditions)
        rows = await q.select(Path(self.model, (parent_pk,))).all()

        parent_ids: list[Any] = [
            self._row_pk_value(r, parent_pk) for r in rows
        ]
        parent_ids = [pid for pid in parent_ids if pid is not None]
        if not parent_ids:
            return

        await self._cascade_delete_for_parent_ids(meta, parent_ids, hard=hard)

    async def _cascade_delete_for_parent_ids(
        self,
        meta: Any,
        parent_ids: list[Any],
        hard: bool = False,
    ) -> None:
        if not parent_ids:
            return

        for rname, rel in meta.relationships.items():
            if rel.is_embedded:
                if self.adapter.nested_documents:
                    continue
                table_name = f"{meta.table}_{rname}"
                embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})
                del_ast = DeleteMany(
                    source=embedded_source,
                    filters=(Path(embedded_source, ("parent_id",)).in_(parent_ids),),
                )
                await self.adapter.execute_mutation(del_ast)

            elif rel.kind == RelationshipKind.MANY_TO_MANY:
                if not rel.through:
                    continue
                target_meta = self._mtm_target_meta(rel)
                if target_meta is None:
                    continue
                local_col, _ = _junction_columns(meta, rel, target_meta)
                junction_source = _junction_source(rel.through)
                del_ast = DeleteMany(
                    source=junction_source,
                    filters=(Path(junction_source, (local_col,)).in_(parent_ids),),
                )
                await self.adapter.execute_mutation(del_ast)

            elif rel.kind in (RelationshipKind.ONE_TO_ONE, RelationshipKind.ONE_TO_MANY):
                target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
                fk_name = rel.foreign_key or f"{to_plural_lower(meta.table)}_id"
                child_condition = Path(target_cls, (fk_name,)).in_(parent_ids)
                if rel.on_delete == "cascade":
                    child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)
                    if hard:
                        await child_repo.hard_delete_many(child_condition)
                    else:
                        await child_repo.delete_many(child_condition)
                elif rel.on_delete == "set null":
                    upd_ast = UpdateMany(
                        source=target_cls,
                        values={fk_name: None},
                        filters=(child_condition,),
                    )
                    await self.adapter.execute_mutation(upd_ast)
                elif rel.on_delete == "set default":
                    upd_ast = UpdateMany(
                        source=target_cls,
                        values={fk_name: self._fk_default(target_cls, fk_name)},
                        filters=(child_condition,),
                    )
                    await self.adapter.execute_mutation(upd_ast)
                elif rel.on_delete == "restrict":
                    child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)
                    if await child_repo.exists(child_condition):
                        raise IntegrityError(
                            f"cannot delete {meta.table} because related {target_cls.__name__} "
                            f"rows still reference the parent"
                        )


    @staticmethod
    def _fk_default(target_cls: type, fk_name: str) -> Any:
        meta = getattr(target_cls, "__db_metadata__", None)
        if meta is None:
            return None
        fmeta = meta.fields.get(fk_name)
        if fmeta is None:
            return None
        return fmeta.get_default()

    async def cascade_on_update(self, obj: Any) -> None:
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return

        pk = meta.primary_key_field
        old_id = getattr(obj, "_db_original_snapshot", {}).get(pk)
        new_id = getattr(obj, pk, None)
        if old_id is None or old_id == new_id:
            return

        for rname, rel in meta.relationships.items():
            if rel.is_embedded:
                continue
            if rel.kind == RelationshipKind.MANY_TO_MANY:
                if not rel.through:
                    continue
                target_meta = self._mtm_target_meta(rel)
                if target_meta is None:
                    continue
                local_col, _ = _junction_columns(meta, rel, target_meta)
                junction_source = _junction_source(rel.through)
                upd_ast = UpdateMany(
                    source=junction_source,
                    values={local_col: new_id},
                    filters=(Path(junction_source, (local_col,)) == old_id,),
                )
                await self.adapter.execute_mutation(upd_ast)
                continue
            if rel.kind not in (RelationshipKind.ONE_TO_ONE, RelationshipKind.ONE_TO_MANY):
                continue
            action = rel.on_update
            if action not in ("cascade", "set null", "set default", "restrict"):
                continue
            target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
            fk_name = rel.foreign_key or f"{to_plural_lower(meta.table)}_id"
            condition = Path(target_cls, (fk_name,)) == old_id
            if action == "cascade":
                values = {fk_name: new_id}
            elif action == "set null":
                values = {fk_name: None}
            elif action == "set default":
                values = {fk_name: self._fk_default(target_cls, fk_name)}
            else:
                child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)
                if await child_repo.exists(condition):
                    raise IntegrityError(
                        f"cannot update {meta.table} because related {target_cls.__name__} "
                        f"rows still reference the parent"
                    )
                continue
            upd_ast = UpdateMany(
                source=target_cls,
                values=values,
                filters=(condition,),
            )
            await self.adapter.execute_mutation(upd_ast)

    @staticmethod
    def _row_pk_value(row: Any, pk: str) -> Any:
        if isinstance(row, dict):
            return row.get(pk)
        return getattr(row, pk, None)

