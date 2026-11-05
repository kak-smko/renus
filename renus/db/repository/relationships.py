from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from renus.db.core.exceptions import IntegrityError
from renus.db.mutation.ast import (
    DeleteMany,
    InsertMany,
    Update,
    UpdateMany,
)
from renus.db.query.ast import Condition, Path
from renus.datastructures.id import ID
from renus.db.relationships import RelationshipKind

from renus.db.transaction.core import Transaction
from renus.util import to_plural_lower



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

        snapshot = getattr(obj, "_db_original_snapshot", {}) or {}
        pk = meta.primary_key_field
        pk_changed = (
            snapshot.get(pk) is not None
            and snapshot.get(pk) != getattr(obj, pk, None)
        )
        persisted = not getattr(obj, "model_is_new", lambda: True)()

        for rname, rel in meta.relationships.items():
            value = getattr(obj, rname, None)

            if rel.kind in (
                RelationshipKind.ONE_TO_MANY,
                RelationshipKind.ONE_TO_ONE,
            ):
                if rel.on_save == "cascade" and value:
                    return True
                if persisted and rel.on_update in (
                    "cascade",
                    "set null",
                    "set default",
                    "restrict",
                ):
                    local_key = rel.local_key or pk
                    old_value = snapshot.get(local_key)
                    new_value = getattr(obj, local_key, None)
                    if old_value is not None and old_value != new_value:
                        return True

            elif rel.kind == RelationshipKind.MANY_TO_ONE and rel.on_save == "cascade":
                return True

            elif rel.kind == RelationshipKind.MANY_TO_MANY:
                if value or (persisted and pk_changed):
                    return True

        return False

    async def persist_relationships(
        self,
        obj: Any,
        *,
        preserve_foreign_keys: set[int] | None = None,
    ) -> None:
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

            if rel.kind == RelationshipKind.ONE_TO_MANY and (
                rel.on_save == "cascade"
            ):
                local_value = self._local_key_value(obj, rel, parent_id)
                await self._persist_one_to_many(
                    meta, rel, local_value, val, preserve_foreign_keys
                )

            elif rel.kind == RelationshipKind.ONE_TO_ONE and (
                rel.on_save == "cascade"
            ):
                local_value = self._local_key_value(obj, rel, parent_id)
                await self._persist_one_to_one(
                    meta, rel, local_value, val, preserve_foreign_keys
                )

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


    async def _persist_one_to_one(
        self,
        parent_meta: Any,
        rel: Any,
        local_value: Any,
        child: Any,
        preserve_foreign_keys: set[int] | None = None,
    ) -> None:
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)

        fk_name = rel.foreign_key or f"{to_plural_lower(parent_meta.table)}_id"
        if preserve_foreign_keys is None or id(child) not in preserve_foreign_keys:
            object.__setattr__(child, fk_name, local_value)
        await child_repo.save(child)

    async def _persist_one_to_many(
        self,
        parent_meta: Any,
        rel: Any,
        local_value: Any,
        children: Iterable[Any],
        preserve_foreign_keys: set[int] | None = None,
    ) -> None:
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)

        fk_name = rel.foreign_key or f"{to_plural_lower(parent_meta.table)}_id"

        for child in children:
            if preserve_foreign_keys is None or id(child) not in preserve_foreign_keys:
                object.__setattr__(child, fk_name, local_value)
            await child_repo.save(child)

    @staticmethod
    def _local_key_value(obj: Any, rel: Any, parent_id: Any) -> Any:
        """Return the owner value related rows must store as their foreign key.

        A configured ``local_key`` takes precedence even when its value is
        ``None``; falling back to the primary key would create a false link.
        """
        if rel.local_key is None:
            return parent_id
        return getattr(obj, rel.local_key, None)

    async def cascade_delete(self, obj: Any, hard: bool = False) -> None:
        """Cascade-delete related rows for a single model object."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return

        parent_pk = meta.primary_key_field
        snapshot = getattr(obj, "_db_original_snapshot", {}) or {}
        parent_id = snapshot.get(parent_pk, getattr(obj, parent_pk, None))
        if parent_id is None:
            return

        for rname, rel in meta.relationships.items():
            if rel.kind not in (RelationshipKind.ONE_TO_ONE, RelationshipKind.ONE_TO_MANY):
                continue
            local_key = rel.local_key or parent_pk
            local_value = snapshot.get(local_key, getattr(obj, local_key, None))
            if local_value is not None:
                await self._cascade_delete_for_parent_ids(
                    meta, [local_value], hard=hard, relationships={rname}
                )

        await self._cascade_delete_for_parent_ids(
            meta,
            [parent_id],
            hard=hard,
            relationships={
                name
                for name, rel in meta.relationships.items()
                if rel.kind == RelationshipKind.MANY_TO_MANY
            },
        )

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
        dependent_relationships = [
            (name, rel, rel.local_key or parent_pk)
            for name, rel in meta.relationships.items()
            if rel.kind in (RelationshipKind.ONE_TO_ONE, RelationshipKind.ONE_TO_MANY)
        ]
        selected_fields = [parent_pk]
        for _, _, local_key in dependent_relationships:
            if local_key not in selected_fields:
                selected_fields.append(local_key)

        q = self.repo.query()
        if hard:
            q = q.with_deleted()
        if conditions:
            q = q.where(*conditions)
        rows = await q.select(
            *(Path(self.model, (field,)) for field in selected_fields)
        ).all()

        for rname, rel, local_key in dependent_relationships:
            local_values = list(
                dict.fromkeys(
                    value
                    for row in rows
                    if (value := self._row_pk_value(row, local_key)) is not None
                )
            )
            await self._cascade_delete_for_parent_ids(
                meta, local_values, hard=hard, relationships={rname}
            )

        parent_ids = list(
            dict.fromkeys(
                value
                for row in rows
                if (value := self._row_pk_value(row, parent_pk)) is not None
            )
        )
        await self._cascade_delete_for_parent_ids(
            meta,
            parent_ids,
            hard=hard,
            relationships={
                name
                for name, rel in meta.relationships.items()
                if rel.kind == RelationshipKind.MANY_TO_MANY
            },
        )

    async def _cascade_delete_for_parent_ids(
        self,
        meta: Any,
        parent_ids: list[Any],
        hard: bool = False,
        relationships: set[str] | None = None,
    ) -> None:
        if not parent_ids:
            return

        for rname, rel in meta.relationships.items():
            if relationships is not None and rname not in relationships:
                continue
            if rel.kind == RelationshipKind.MANY_TO_MANY:
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
                related_ids = self._coerce_related_ids(target_cls, fk_name, parent_ids)
                child_condition = Path(target_cls, (fk_name,)).in_(related_ids)
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
    def _coerce_related_ids(target_cls: type, fk_name: str, values: list[Any]) -> list[Any]:
        """Coerce owner keys to the declared type of the child foreign key."""
        target_meta = getattr(target_cls, "__db_metadata__", None)
        field_meta = target_meta.fields.get(fk_name) if target_meta else None
        target_type = field_meta.inferred_type if field_meta else None
        coerced: list[Any] = []
        for value in values:
            if isinstance(value, ID):
                value = value.value
                if target_type is str and value is not None:
                    value = str(value)
                elif target_type is ID and value is not None:
                    value = ID(value)
            coerced.append(value)
        return coerced

    @staticmethod
    def _fk_default(target_cls: type, fk_name: str) -> Any:
        meta = getattr(target_cls, "__db_metadata__", None)
        if meta is None:
            return None
        fmeta = meta.fields.get(fk_name)
        if fmeta is None:
            return None
        return fmeta.get_default()

    async def cascade_on_update(self, obj: Any) -> set[int]:
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return set()

        snapshot = getattr(obj, "_db_original_snapshot", {}) or {}
        pk = meta.primary_key_field
        old_pk = snapshot.get(pk)
        new_pk = getattr(obj, pk, None)
        pk_changed = old_pk is not None and old_pk != new_pk
        preserve_foreign_keys: set[int] = set()
        lock_parent = False
        keys_to_verify: dict[str, Any] = {}

        for rel in meta.relationships.values():
            if (
                rel.kind == RelationshipKind.MANY_TO_MANY
                and pk_changed
                and rel.through
            ):
                lock_parent = True
            if rel.kind not in (RelationshipKind.ONE_TO_ONE, RelationshipKind.ONE_TO_MANY):
                continue
            local_key = rel.local_key or pk
            old_value = old_pk if local_key == pk else snapshot.get(local_key)
            new_value = new_pk if local_key == pk else getattr(obj, local_key, None)
            if (
                old_value is not None
                and old_value != new_value
                and rel.on_update in ("cascade", "set null", "set default", "restrict")
            ):
                lock_parent = True
                keys_to_verify[local_key] = old_value

        if lock_parent and self.adapter.need_locked_parent:
            locked_parent = await self.repo.query(
                Path(self.model, (pk,)) == old_pk
            ).first()
            if locked_parent is None:
                raise IntegrityError(
                    f"cannot update {meta.table} because the persisted parent row no longer exists"
                )
            for local_key, old_value in keys_to_verify.items():
                if getattr(locked_parent, local_key, None) != old_value:
                    raise IntegrityError(
                        f"cannot update {meta.table} because its {local_key} key changed concurrently"
                    )

        for rel in meta.relationships.values():
            if rel.kind == RelationshipKind.MANY_TO_MANY:
                if not pk_changed or not rel.through:
                    continue
                target_meta = self._mtm_target_meta(rel)
                if target_meta is None:
                    continue
                local_col, _ = _junction_columns(meta, rel, target_meta)
                junction_source = _junction_source(rel.through)
                upd_ast = UpdateMany(
                    source=junction_source,
                    values={local_col: new_pk},
                    filters=(Path(junction_source, (local_col,)) == old_pk,),
                )
                await self.adapter.execute_mutation(upd_ast)
                continue
            if rel.kind not in (RelationshipKind.ONE_TO_ONE, RelationshipKind.ONE_TO_MANY):
                continue


            local_key = rel.local_key or pk
            if local_key == pk:
                old_value, new_value = old_pk, new_pk
            else:
                old_value = snapshot.get(local_key)
                new_value = getattr(obj, local_key, None)
            if old_value is None or old_value == new_value:
                continue

            action = rel.on_update
            if action not in ("cascade", "set null", "set default", "restrict"):
                continue
            target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
            fk_name = rel.foreign_key or f"{to_plural_lower(meta.table)}_id"
            condition = Path(target_cls, (fk_name,)) == old_value
            if action == "cascade":
                values = {fk_name: new_value}
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
            self._sync_loaded_related_children(
                obj,
                rel,
                fk_name,
                old_value,
                values[fk_name],
                preserve_foreign_keys,
                preserve_foreign_key=action != "cascade",
            )

        return preserve_foreign_keys

    @staticmethod
    def _sync_loaded_related_children(
        obj: Any,
        rel: Any,
        fk_name: str,
        old_value: Any,
        new_value: Any,
        preserve_foreign_keys: set[int],
        *,
        preserve_foreign_key: bool,
    ) -> None:
        children = getattr(obj, rel.name, None)
        if children is None:
            return
        if not isinstance(children, (list, tuple, set)):
            children = (children,)

        for child in children:
            current_fk = (
                child.get(fk_name) if isinstance(child, dict)
                else getattr(child, fk_name, None)
            )
            if current_fk != old_value:
                continue

            if isinstance(child, dict):
                child[fk_name] = new_value
                continue

            setattr(child, fk_name, new_value)
            child_meta = getattr(child, "__db_metadata__", None)
            if child_meta and fk_name in child_meta.identity.fields:
                child_snapshot = getattr(child, "_db_original_snapshot", None)
                if child_snapshot is not None:
                    child_snapshot[fk_name] = new_value
            if preserve_foreign_key:
                preserve_foreign_keys.add(id(child))

    @staticmethod
    def _row_pk_value(row: Any, pk: str) -> Any:
        if isinstance(row, dict):
            return row.get(pk)
        return getattr(row, pk, None)

