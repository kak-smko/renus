from __future__ import annotations

import importlib
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID

from renus.db.core.exceptions import ValidationError
from renus.db.models.base import ReModel
from renus.db.models.id import ID

__all__ = [
    "from_dict",
    "from_json",
    "sanitize_params",
    "to_dict",
    "to_json",
]

T = TypeVar("T")


def _resolve_declared_type(model_cls: type[Any], target_type: Any) -> Any:
    """Resolve a string annotation from its model module namespace."""
    if not hasattr(model_cls, "__module__"):
        return None
    namespace = vars(importlib.import_module(model_cls.__module__))
    return namespace.get(str(target_type))


def to_dict(
    value: Any,
    *,
    exclude_none: bool = False,
    exclude_unset: bool = False,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    include_sensitive: bool = False,
) -> Any:
    """Convert a value into a JSON-serializable dict, optionally filtering fields."""
    inc_set = set(include) if include is not None else None
    exc_set = set(exclude) if exclude is not None else set()

    if isinstance(value, ReModel):
        meta = getattr(value, "__db_metadata__", None)
        out: dict[str, Any] = {}
        fields_to_process = meta.fields.keys() if meta else value.__dict__.keys()

        for fname in fields_to_process:
            if fname.startswith("_") and fname != "_id":
                continue
            if inc_set is not None and fname not in inc_set:
                continue
            if fname in exc_set:
                continue

            if meta and meta.fields.get(fname) and meta.fields[fname].sensitive:
                if not include_sensitive:
                    continue
                out[fname] = to_dict(
                    value.get_sensitive(fname),
                    exclude_none=exclude_none,
                    exclude_unset=exclude_unset,
                    include_sensitive=include_sensitive,
                )
                continue

            val = getattr(value, fname, None)

            if exclude_none and val is None:
                continue
            if exclude_unset and fname not in value.__dict__:
                continue

            out[fname] = to_dict(
                val,
                exclude_none=exclude_none,
                exclude_unset=exclude_unset,
                include_sensitive=include_sensitive,
            )

        if meta and meta.relationships:
            for rname in meta.relationships:
                if inc_set is not None and rname not in inc_set:
                    continue
                if rname in exc_set:
                    continue
                if rname in value.__dict__:
                    rval = value.__dict__[rname]
                    if exclude_none and rval is None:
                        continue
                    out[rname] = to_dict(
                        rval,
                        exclude_none=exclude_none,
                        exclude_unset=exclude_unset,
                        include_sensitive=include_sensitive,
                    )

        return out

    if isinstance(value, Mapping):
        return {
            str(k): to_dict(v, exclude_none=exclude_none, exclude_unset=exclude_unset)
            for k, v in value.items()
            if not (exclude_none and v is None)
        }

    if isinstance(value, (list, tuple, set)):
        return [
            to_dict(item, exclude_none=exclude_none, exclude_unset=exclude_unset)
            for item in value
        ]

    if isinstance(value, ID):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (bytes, bytearray)):
        return value.hex()

    return value

def from_dict(
    model_cls: type[T],
    data: dict[str, Any],
    *,
    validate: bool = True,
) -> T:
    """Instantiate and populate a model instance from a dict of field values."""
    if not isinstance(data, dict):
        raise ValidationError(f"Expected dict input for {model_cls.__name__}, got {type(data).__name__}")

    if not issubclass(model_cls, ReModel):
        return model_cls(**data)

    meta = getattr(model_cls, "__db_metadata__", None)
    cleaned_data = dict(data)

    if meta:
        for fname, fmeta in meta.fields.items():
            if fname not in cleaned_data:
                continue
            raw_val = cleaned_data[fname]
            if raw_val is None:
                continue

            target_type = fmeta.python_type
            target_str = str(getattr(fmeta, "inferred_type", None) or target_type).lower()
            storage_type = getattr(fmeta, "storage_type", None)

            if target_type is ID or storage_type is ID or "id" == target_str.rsplit(".", 1)[-1]:
                cleaned_data[fname] = ID(raw_val)

            elif (storage_type is UUID or target_type is UUID or (storage_type is None and "uuid" in target_str)) and isinstance(raw_val, str):
                try:
                    cleaned_data[fname] = UUID(raw_val)
                except Exception:
                    pass

            elif (storage_type is datetime or target_type is datetime or (storage_type is None and "datetime" in target_str)) and isinstance(raw_val, str):
                try:
                    cleaned_data[fname] = datetime.fromisoformat(raw_val)
                except Exception:
                    pass

            elif (storage_type is date or target_type is date or (storage_type is None and "date" in target_str and "datetime" not in target_str)) and isinstance(raw_val, str):
                try:
                    cleaned_data[fname] = date.fromisoformat(raw_val)
                except Exception:
                    pass

            elif (storage_type is Decimal or target_type is Decimal or (storage_type is None and "decimal" in target_str)) and isinstance(raw_val, (str, int, float)):
                try:
                    cleaned_data[fname] = Decimal(str(raw_val))
                except Exception:
                    pass

            elif isinstance(raw_val, str):
                enum_cls = None
                if isinstance(target_type, type) and issubclass(target_type, Enum):
                    enum_cls = target_type
                elif isinstance(fmeta.default, Enum):
                    enum_cls = type(fmeta.default)
                else:
                    declared_type = _resolve_declared_type(model_cls, target_type)
                    if isinstance(declared_type, type) and issubclass(declared_type, Enum):
                        enum_cls = declared_type
                if enum_cls is not None:
                    try:
                        cleaned_data[fname] = enum_cls(raw_val)
                    except Exception:
                        pass

            elif isinstance(raw_val, dict):
                target_model_cls = None
                if isinstance(target_type, type) and issubclass(target_type, ReModel):
                    target_model_cls = target_type
                elif fname in meta.relationships:
                    rel = meta.relationships[fname]
                    if isinstance(rel.target, type) and issubclass(rel.target, ReModel):
                        target_model_cls = rel.target
                else:
                    declared_type = _resolve_declared_type(model_cls, target_type)
                    if isinstance(declared_type, type) and issubclass(declared_type, ReModel):
                        target_model_cls = declared_type

                if target_model_cls is not None:
                    cleaned_data[fname] = from_dict(target_model_cls, raw_val, validate=validate)

    if validate:
        return model_cls.validate(cleaned_data)
    return model_cls(cleaned_data)

class _DBJSONEncoder(json.JSONEncoder):

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date, time)):
            return o.isoformat()
        if isinstance(o, (UUID, ID)):
            return str(o)
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, (bytes, bytearray)):
            return o.hex()
        return super().default(o)

def to_json(value: Any, *, indent: int | None = None, **kwargs: Any) -> str:
    """Serialize a value to a JSON string."""
    dict_val = to_dict(value)
    return json.dumps(dict_val, cls=_DBJSONEncoder, indent=indent, **kwargs)

def from_json(
    model_cls: type[T],
    json_data: str | bytes,
    *,
    validate: bool = True,
) -> T:
    """Deserialize a JSON string into a model instance."""
    parsed = json.loads(json_data)
    return from_dict(model_cls, parsed, validate=validate)

def sanitize_params(value: Any, *, mask: str = "***") -> Any:
    """Recursively replace sensitive field values with a mask."""
    if isinstance(value, ReModel):
        meta = getattr(value, "__db_metadata__", None)
        fields = meta.fields if meta else {}
        out: dict[str, Any] = {}
        for fname, fmeta in fields.items():
            if fname.startswith("_") and fname != "_id":
                continue
            if fmeta.sensitive:
                out[fname] = mask
            else:
                out[fname] = sanitize_params(getattr(value, fname, None), mask=mask)

        if meta and meta.relationships:
            for rname in meta.relationships:
                if rname in value.__dict__:
                    out[rname] = sanitize_params(value.__dict__[rname], mask=mask)
        return out

    if isinstance(value, Mapping):
        return {str(k): sanitize_params(v, mask=mask) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [sanitize_params(item, mask=mask) for item in value]

    return value
