from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from renus.db.models.id import ID

__all__ = ["decode_value", "encode_value"]


def encode_value(value: Any, field_meta: Any = None) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def decode_value(value: Any, field_meta: Any = None) -> Any:
    if value is None or field_meta is None:
        return value


    target_type = field_meta.inferred_type
    type_str = str(target_type).lower()

    if target_type is ID or "id" == type_str.rsplit(".", 1)[-1]:
        return ID(value)

    if (target_type is bool or type_str in ("bool", "boolean")) and isinstance(value, int):
        return bool(value)

    if (
        target_type is datetime or type_str.rsplit(".", 1)[-1] == "datetime"
    ) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value.rstrip("Z"))
        except Exception:
            return value

    if (
        target_type is date or type_str.rsplit(".", 1)[-1] == "date"
    ) and isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except Exception:
            return value

    if (
        target_type is time or type_str.rsplit(".", 1)[-1] == "time"
    ) and isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except Exception:
            return value

    if (target_type is UUID or "uuid" in type_str) and isinstance(value, str):
        try:
            return UUID(value)
        except Exception:
            return value

    if (target_type is Decimal or "decimal" in type_str) and isinstance(value, (str, int, float)):
        try:
            return Decimal(str(value))
        except Exception:
            return value

    if (
        target_type in (dict, list)
        or getattr(target_type, "__origin__", None) in (dict, list)
        or type_str.startswith("dict")
        or type_str.startswith("list")
    ) and isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value

    return value
