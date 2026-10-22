from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, get_args, get_origin
from uuid import UUID

from renus.datastructures.id import ID


def _encode_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, (UUID, ID)):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _json_value(value: Any, field_meta: Any = None, expected_type: Any = None) -> Any:
    if value is None:
        return None

    if expected_type in (bytes, bytearray) and isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()

    if hasattr(value, "__db_metadata__"):
        model_meta = value.__db_metadata__
        encoded: dict[str, Any] = {}
        for key in value._model_fields:
            nested_field = model_meta.fields.get(key)
            item = value.get_sensitive(key) if nested_field and nested_field.sensitive else getattr(value, key, None)
            encoded[key] = _json_value(
                item,
                nested_field,
                getattr(nested_field, "python_type", None),
            )
        return encoded

    if isinstance(value, dict):
        type_args = get_args(expected_type or getattr(field_meta, "python_type", None))
        value_type = type_args[1] if len(type_args) == 2 else None
        nested_fields = getattr(field_meta, "fields", {})
        result = {}
        for key, item in value.items():
            child_meta = nested_fields.get(key) if nested_fields else None
            result[str(_encode_scalar(key))] = _json_value(
                item,
                child_meta,
                getattr(child_meta, "python_type", value_type),
            )
        return result

    if isinstance(value, (list, tuple, set)):
        type_args = get_args(expected_type or getattr(field_meta, "python_type", None))
        item_type = type_args[0] if type_args else getattr(field_meta, "model_cls", None)
        return [_json_value(item, None, item_type) for item in value]

    return _encode_scalar(value)


def encode_value(value: Any, field_meta: Any = None) -> Any:
    if isinstance(value, (dict, list, tuple, set)) or hasattr(value, "__db_metadata__"):
        expected_type = getattr(field_meta, "python_type", None)
        return json.dumps(_json_value(value, field_meta, expected_type))
    return _encode_scalar(value)


def _decode_typed(value: Any, expected_type: Any) -> Any:
    if value is None or expected_type is None or expected_type is Any:
        return value

    origin = get_origin(expected_type)
    args = get_args(expected_type)
    if origin is list:
        item_type = args[0] if args else None
        return [_decode_typed(item, item_type) for item in value] if isinstance(value, list) else value
    if origin is dict:
        key_type, value_type = args if len(args) == 2 else (None, None)
        if not isinstance(value, dict):
            return value
        return {
            _decode_typed(key, key_type): _decode_typed(item, value_type)
            for key, item in value.items()
        }

    if isinstance(expected_type, type):
        if expected_type is ID:
            return value if isinstance(value, ID) else ID(value)
        if expected_type in (bytes, bytearray) and isinstance(value, str):
            try:
                decoded = bytes.fromhex(value)
                return decoded if expected_type is bytes else bytearray(decoded)
            except ValueError:
                return value
        if expected_type is bool:
            return bool(value)
        if expected_type in (int, float, str):
            return value if isinstance(value, expected_type) else expected_type(value)
        if expected_type is UUID and isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                return value
        if expected_type is Decimal and isinstance(value, (str, int, float)):
            try:
                return Decimal(str(value))
            except Exception:
                return value
        if expected_type is datetime and isinstance(value, str):
            try:
                return datetime.fromisoformat(value.rstrip("Z"))
            except ValueError:
                return value
        if expected_type is date and isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return value
        if expected_type is time and isinstance(value, str):
            try:
                return time.fromisoformat(value)
            except ValueError:
                return value
        if getattr(expected_type, "_is_model_class", False) and isinstance(value, dict):
            from renus.db.serialization.core import from_dict

            return from_dict(expected_type, value)
    return value


def _resolve_custom_type(field_meta: Any) -> type | None:
    target_type = getattr(field_meta, "python_type", None)
    if not isinstance(target_type, type):
        target_type = getattr(field_meta, "inferred_type", None)
    if isinstance(target_type, type) and target_type not in (
        bool, int, float, str, bytes, bytearray, date, datetime, time, Decimal, UUID,
    ):
        return target_type
    return None
    
def decode_value(value: Any, field_meta: Any = None) -> Any:
    if value is None or field_meta is None:
        return value

    storage_type = getattr(field_meta, "storage_type", None)
    if isinstance(value, str) and storage_type in (dict, list):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    if storage_type in (dict, list):
        return _decode_typed(value, getattr(field_meta, "python_type", None))

    target_type = field_meta.inferred_type
    type_str = str(target_type).lower()


    custom_type = _resolve_custom_type(field_meta)
    if custom_type is not None and isinstance(value, str):
        try:
            return custom_type(value)
        except Exception:
                pass
                
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
        getattr(field_meta, "storage_type", None) in (dict, list)
        or target_type in (dict, list)
        or getattr(target_type, "__origin__", None) in (dict, list)
        or type_str.startswith("dict")
        or type_str.startswith("list")
    ) and isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value

    return value
