from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from renus.db.mutation.ast import (
    Delete,
    Insert,
    InsertMany,
    Update,
)
from renus.db.query.ast import Condition, Include, Path
from renus.db.relationships import RelationshipKind
from renus.db.serialization.core import to_dict
from renus.db.transaction.core import Transaction

__all__ = ["RelationshipCoordinator"]

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
    async def _atomic(self) -> AsyncIterator[None]:
        if self.adapter._in_active_transaction():
            yield
            return
        async with Transaction(self.adapter):
            yield

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
                else:
                    await self._persist_embedded_many(meta, rname, rel, parent_id, val)

            elif rel.kind == RelationshipKind.ONE_TO_MANY and (
                "all" in rel.cascade or "save" in rel.cascade
            ):
                await self._persist_one_to_many(meta, rel, parent_id, val)

            elif rel.kind == RelationshipKind.ONE_TO_ONE and (
                "all" in rel.cascade or "save" in rel.cascade
            ):
                await self._persist_one_to_one(meta, rel, parent_id, val)

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
    ) -> None:
        if rel.target is dict:
            return await self._persist_raw_embedded_one(
                parent_meta, rel_name, parent_id, child
            )

        child_dict = child.to_dict() if hasattr(child, "to_dict") else dict(child)
        child_dict["parent_id"] = parent_id

        child_meta = getattr(child, "__db_metadata__", None)
        if child_meta is not None:
            pk_fmeta = child_meta.fields.get(child_meta.primary_key_field)
            if pk_fmeta is not None and pk_fmeta.generated:
                child_dict.pop("id", None)

        table_name = f"{parent_meta.table}_{rel_name}"

        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        async with self._atomic():
            del_ast = Delete(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            ins_ast = Insert(source=embedded_source, values=child_dict)
            await self.adapter.execute_mutation(ins_ast)

    async def _persist_embedded_many(
        self,
        parent_meta: Any,
        rel_name: str,
        rel: Any,
        parent_id: Any,
        items: Iterable[Any],
    ) -> None:
        if rel.target is list:
            return await self._persist_raw_embedded_many(
                parent_meta, rel_name, parent_id, items
            )

        table_name = f"{parent_meta.table}_{rel_name}"
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        records: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            d = item.to_dict() if hasattr(item, "to_dict") else dict(item)
            d["parent_id"] = parent_id
            item_meta = getattr(item, "__db_metadata__", None)
            if item_meta is not None:
                pk_fmeta = item_meta.fields.get(item_meta.primary_key_field)
                if pk_fmeta is not None and pk_fmeta.generated:
                    d.pop("id", None)
            records.append(d)

        async with self._atomic():
            del_ast = Delete(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            if records:
                ins_many = InsertMany(source=embedded_source, records=records)
                await self.adapter.execute_mutation(ins_many)

    async def _persist_raw_embedded_one(
        self,
        parent_meta: Any,
        rel_name: str,
        parent_id: Any,
        data: dict[str, Any] | None,
    ) -> None:
        table_name = f"{parent_meta.table}_{rel_name}"
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        async with self._atomic():
            del_ast = Delete(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            if not data:
                return
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
    ) -> None:
        table_name = f"{parent_meta.table}_{rel_name}"
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        records = [
            {"parent_id": parent_id, "pos": idx, "value": _string_value(item)}
            for idx, item in enumerate(items)
        ]

        async with self._atomic():
            del_ast = Delete(
                source=embedded_source,
                filters=(Path(embedded_source, ("parent_id",)) == parent_id,),
            )
            await self.adapter.execute_mutation(del_ast)

            if records:
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

        fk_name = rel.foreign_key or f"{parent_meta.table[:-1] if parent_meta.table.endswith('s') else parent_meta.table}_id"
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

        fk_name = rel.foreign_key or f"{parent_meta.table[:-1] if parent_meta.table.endswith('s') else parent_meta.table}_id"

        for child in children:
            object.__setattr__(child, fk_name, parent_id)
            await child_repo.save(child)

    async def cascade_delete(self, obj: Any) -> None:
        """Cascade-delete related rows for a single model object."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return

        parent_pk = meta.primary_key_field
        parent_id = getattr(obj, parent_pk, None)
        if parent_id is None:
            return

        await self._cascade_delete_for_parent_ids(meta, [parent_id])

    async def cascade_delete_many(
        self,
        *conditions: Condition,
        limit: int | None = None,
    ) -> None:
        """Cascade-delete related rows for all rows matching the conditions."""
        meta = getattr(self.model, "__db_metadata__", None)
        if not meta or not meta.relationships:
            return

        parent_pk = meta.primary_key_field
        q = self.repo.query()
        if conditions:
            q = q.where(*conditions)
        if limit is not None:
            q = q.limit(limit)
        rows = await q.select(Path(self.model, (parent_pk,))).all()

        parent_ids: list[Any] = [
            self._row_pk_value(r, parent_pk) for r in rows
        ]
        parent_ids = [pid for pid in parent_ids if pid is not None]
        if not parent_ids:
            return

        await self._cascade_delete_for_parent_ids(meta, parent_ids)

    async def _cascade_delete_for_parent_ids(
        self,
        meta: Any,
        parent_ids: list[Any],
    ) -> None:
        if not parent_ids:
            return

        for rname, rel in meta.relationships.items():
            if rel.is_embedded:
                if self.adapter.nested_documents:
                    continue
                table_name = f"{meta.table}_{rname}"
                embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})
                del_ast = Delete(
                    source=embedded_source,
                    filters=(Path(embedded_source, ("parent_id",)).in_(parent_ids),),
                )
                await self.adapter.execute_mutation(del_ast)

            elif "all" in rel.cascade or "delete" in rel.cascade or rel.on_delete == "cascade":
                target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
                fk_name = rel.foreign_key or f"{meta.table[:-1] if meta.table.endswith('s') else meta.table}_id"
                child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)
                await child_repo.delete_many(Path(target_cls, (fk_name,)).in_(parent_ids))

    @staticmethod
    def _row_pk_value(row: Any, pk: str) -> Any:
        if isinstance(row, dict):
            return row.get(pk)
        return getattr(row, pk, None)

    async def load_includes(self, objects: list[Any], includes: tuple[Include, ...]) -> None:
        """Eagerly load the requested relationships onto the given objects."""
        if not objects or not includes:
            return

        meta = getattr(self.model, "__db_metadata__", None)
        if not meta:
            return

        parent_pk = meta.primary_key_field
        parent_ids = [getattr(o, parent_pk) for o in objects if getattr(o, parent_pk, None) is not None]
        if not parent_ids:
            return

        for inc in includes:
            rel_name = inc.path.parts[0]
            rel = meta.relationships.get(rel_name)
            if not rel:
                continue

            if rel.kind == RelationshipKind.EMBEDDED_ONE:
                if not self.adapter.nested_documents:
                    await self._load_embedded_one_batch(meta, rel_name, rel, parent_ids, objects)

            elif rel.kind == RelationshipKind.EMBEDDED_MANY:
                if not self.adapter.nested_documents:
                    await self._load_embedded_many_batch(meta, rel_name, rel, parent_ids, objects)

            elif rel.kind == RelationshipKind.ONE_TO_MANY:
                await self._load_one_to_many_batch(meta, rel_name, rel, parent_ids, objects, inc)

            elif rel.kind == RelationshipKind.MANY_TO_ONE:
                await self._load_many_to_one_batch(meta, rel_name, rel, objects, inc)

            elif rel.kind == RelationshipKind.ONE_TO_ONE:
                await self._load_one_to_one_batch(meta, rel_name, rel, parent_ids, objects, inc)

    async def _load_embedded_one_batch(
        self,
        meta: Any,
        rel_name: str,
        rel: Any,
        parent_ids: list[Any],
        objects: list[Any],
    ) -> None:
        table_name = f"{meta.table}_{rel_name}"
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        from renus.db.query.ast import QueryAST
        q_ast = QueryAST(
            source=embedded_source,
            filters=(Path(embedded_source, ("parent_id",)).in_(parent_ids),),
        )
        rows = await self.adapter.execute_query(q_ast)

        if rel.target is dict:
            maps: dict[Any, dict[str, Any]] = {pid: {} for pid in parent_ids}
            for r in rows:
                row_dict = dict(r)
                pid = row_dict.pop("parent_id", None)
                if pid in maps:
                    maps[pid][str(row_dict.get("key"))] = _string_parse(row_dict.get("value"))
            for obj in objects:
                pid = getattr(obj, meta.primary_key_field, None)
                object.__setattr__(obj, rel_name, maps.get(pid, {}))
            return

        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        child_map: dict[Any, Any] = {}
        for r in rows:
            row_dict = dict(r)
            pid = row_dict.pop("parent_id", None)
            if pid is not None:
                child_map[pid] = target_cls(row_dict)

        for obj in objects:
            pid = getattr(obj, meta.primary_key_field, None)
            if pid in child_map:
                object.__setattr__(obj, rel_name, child_map[pid])

    async def _load_embedded_many_batch(
        self,
        meta: Any,
        rel_name: str,
        rel: Any,
        parent_ids: list[Any],
        objects: list[Any],
    ) -> None:
        table_name = f"{meta.table}_{rel_name}"
        embedded_source = type(table_name, (), {"__db_metadata__": None, "table": table_name})

        from renus.db.query.ast import QueryAST
        q_ast = QueryAST(
            source=embedded_source,
            filters=(Path(embedded_source, ("parent_id",)).in_(parent_ids),),
        )
        rows = await self.adapter.execute_query(q_ast)

        if rel.target is list:
            ordered: dict[Any, list[Any]] = {pid: [] for pid in parent_ids}
            for r in rows:
                row_dict = dict(r)
                pid = row_dict.pop("parent_id", None)
                if pid in ordered:
                    ordered[pid].append((row_dict.get("pos", 0), _string_parse(row_dict.get("value"))))
            for pid, items in ordered.items():
                items.sort(key=lambda t: t[0])
                ordered[pid] = [v for _, v in items]
            for obj in objects:
                pid = getattr(obj, meta.primary_key_field, None)
                object.__setattr__(obj, rel_name, ordered.get(pid, []))
            return

        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        items_map: dict[Any, list[Any]] = {pid: [] for pid in parent_ids}
        for r in rows:
            row_dict = dict(r)
            pid = row_dict.pop("parent_id", None)
            if pid in items_map:
                items_map[pid].append(target_cls(row_dict))

        for obj in objects:
            pid = getattr(obj, meta.primary_key_field, None)
            object.__setattr__(obj, rel_name, items_map.get(pid, []))

    async def _load_one_to_many_batch(
        self,
        meta: Any,
        rel_name: str,
        rel: Any,
        parent_ids: list[Any],
        objects: list[Any],
        inc: Include,
    ) -> None:
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        fk_name = rel.foreign_key or f"{meta.table[:-1] if meta.table.endswith('s') else meta.table}_id"
        child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)

        filter_cond = Path(target_cls, (fk_name,)).in_(parent_ids)
        if inc.filter is not None:
            filter_cond = filter_cond & inc.filter

        q = child_repo.query(filter_cond)
        if inc.nested:
            q = q.include(*inc.nested)
        children = await q.all()

        grouped: dict[Any, list[Any]] = {pid: [] for pid in parent_ids}
        for child in children:
            child_fk_val = getattr(child, fk_name, None)
            if child_fk_val in grouped:
                grouped[child_fk_val].append(child)

        for obj in objects:
            pid = getattr(obj, meta.primary_key_field, None)
            object.__setattr__(obj, rel_name, grouped.get(pid, []))

    async def _load_many_to_one_batch(
        self,
        meta: Any,
        rel_name: str,
        rel: Any,
        objects: list[Any],
        inc: Include,
    ) -> None:
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        target_meta = getattr(target_cls, "__db_metadata__", None)
        target_pk = target_meta.primary_key_field if target_meta else "id"

        local_fk = rel.foreign_key or f"{rel_name}_id"
        target_ids = list({getattr(o, local_fk) for o in objects if getattr(o, local_fk, None) is not None})
        if not target_ids:
            return

        target_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)
        q = target_repo.query(Path(target_cls, (target_pk,)).in_(target_ids))
        if inc.nested:
            q = q.include(*inc.nested)
        targets = await q.all()

        target_map = {getattr(t, target_pk): t for t in targets}
        for obj in objects:
            fk_val = getattr(obj, local_fk, None)
            if fk_val in target_map:
                object.__setattr__(obj, rel_name, target_map[fk_val])

    async def _load_one_to_one_batch(
        self,
        meta: Any,
        rel_name: str,
        rel: Any,
        parent_ids: list[Any],
        objects: list[Any],
        inc: Include,
    ) -> None:
        target_cls = rel.target if isinstance(rel.target, type) else rel.resolve_target()
        fk_name = rel.foreign_key or f"{meta.table[:-1] if meta.table.endswith('s') else meta.table}_id"
        child_repo = self.repo.__class__(self.adapter, target_cls, self.repo.connection_name)

        children = await child_repo.query(Path(target_cls, (fk_name,)).in_(parent_ids)).all()
        child_map = {getattr(c, fk_name): c for c in children}

        for obj in objects:
            pid = getattr(obj, meta.primary_key_field, None)
            if pid in child_map:
                object.__setattr__(obj, rel_name, child_map[pid])
