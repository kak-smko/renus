from __future__ import annotations

import re
import types
import typing
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, get_args, get_origin
from uuid import UUID

from renus.db.core.state import IdentityKind
from renus.db.models.db_field import ObjectId

_OPTIONAL_RE = re.compile(r"^optional\[\s*(.+)\s*\]$", re.IGNORECASE)

def is_optional_type(annotation: Any) -> tuple[bool, Any]:
    """Detect whether an annotation is optional and return its base type."""
    if isinstance(annotation, str):
        clean = annotation.strip()
        clean_lower = clean.lower()

        m = _OPTIONAL_RE.match(clean)
        if m:
            return True, m.group(1).strip()

        if clean_lower.startswith("union[") and clean_lower.endswith("]"):
            inner = clean[6:-1]
            parts = [p.strip() for p in inner.split(",")]
            non_none = [p for p in parts if p.lower() not in ("none", "nonetype")]
            if len(non_none) < len(parts):
                return True, non_none[0] if len(non_none) == 1 else f"Union[{', '.join(non_none)}]"

        if "|" in clean:
            parts = [p.strip() for p in clean.split("|")]
            non_none = [p for p in parts if p.lower() not in ("none", "nonetype")]
            if len(non_none) < len(parts):
                return True, non_none[0] if len(non_none) == 1 else " | ".join(non_none)

        return False, clean

    origin = get_origin(annotation)
    if origin is typing.Union or (
        hasattr(types, "UnionType") and origin is types.UnionType
    ):
        args = get_args(annotation)
        none_type = type(None)
        if none_type in args:
            remaining = [a for a in args if a is not none_type]
            if len(remaining) == 1:
                return True, remaining[0]

            return True, typing.Union[tuple(remaining)]

    return False, annotation

def infer_storage_type(unwrapped_type: Any) -> type | str:
    """Map a Python type annotation to its storage type."""
    if isinstance(unwrapped_type, str):
        type_str = unwrapped_type.strip()
        type_str_lower = type_str.lower()

        is_opt, base = is_optional_type(type_str)
        if is_opt:
            return infer_storage_type(base)

        if type_str_lower in ("int", "integer"):
            return int
        if type_str_lower in ("str", "string", "text"):
            return str
        if type_str_lower in ("float", "double", "real"):
            return float
        if type_str_lower in ("bool", "boolean"):
            return bool
        if type_str_lower in ("bytes", "blob", "binary"):
            return bytes
        if type_str_lower == "decimal":
            return Decimal
        if type_str_lower == "datetime":
            return datetime
        if type_str_lower == "date":
            return date
        if type_str_lower == "time":
            return time
        if type_str_lower == "timedelta":
            return timedelta
        if type_str_lower == "uuid":
            return UUID
        if type_str_lower in ("objectid", "object_id"):
            return ObjectId
        if type_str_lower.startswith("list"):
            return list
        if type_str_lower.startswith("dict"):
            return dict

        return unwrapped_type

    origin = get_origin(unwrapped_type)

    if origin is list or unwrapped_type is list:
        return list
    if origin is dict or unwrapped_type is dict:
        return dict

    if isinstance(unwrapped_type, type):
        if issubclass(unwrapped_type, bool):
            return bool
        if issubclass(unwrapped_type, int):
            return int
        if issubclass(unwrapped_type, float):
            return float
        if issubclass(unwrapped_type, str):
            if issubclass(unwrapped_type, ObjectId) or unwrapped_type.__name__ == "ObjectId":
                return ObjectId
            return str
        if issubclass(unwrapped_type, bytes):
            return bytes
        if issubclass(unwrapped_type, Decimal):
            return Decimal
        if issubclass(unwrapped_type, datetime):
            return datetime
        if issubclass(unwrapped_type, date):
            return date
        if issubclass(unwrapped_type, time):
            return time
        if issubclass(unwrapped_type, timedelta):
            return timedelta
        if issubclass(unwrapped_type, UUID):
            return UUID

    return unwrapped_type

def infer_identity_kind(
    field_name: str,
    field_type: Any,
    storage_type: Any,
    generated: bool = False,
) -> IdentityKind:
    """Infer the identity kind for a field from its storage type."""
    type_name = str(field_type).lower()
    if field_name == "_id" or storage_type is ObjectId or "objectid" in type_name:
        return IdentityKind.OBJECT_ID
    if storage_type is UUID or "uuid" in type_name:
        return IdentityKind.UUID
    if storage_type is int or "int" in type_name:
        return IdentityKind.INTEGER
    if storage_type is str or "str" in type_name:
        return IdentityKind.STRING
    if generated:
        return IdentityKind.GENERATED
    return IdentityKind.STRING

def analyze_field_type(field_type: Any) -> tuple[bool, Any, type | str]:
    """Return nullability, base type, and storage type for a field annotation."""
    is_nullable, base_type = is_optional_type(field_type)
    storage_type = infer_storage_type(base_type)

    if isinstance(base_type, str):
        lookup = {
            "int": int,
            "str": str,
            "float": float,
            "bool": bool,
            "bytes": bytes,
            "decimal": Decimal,
            "datetime": datetime,
            "date": date,
            "time": time,
            "timedelta": timedelta,
            "uuid": UUID,
            "objectid": ObjectId,
            "dict": dict,
            "list": list,
        }
        resolved = lookup.get(base_type.strip().lower())
        if resolved is not None:
            base_type = resolved

    return is_nullable, base_type, storage_type
