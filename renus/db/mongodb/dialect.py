from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from renus.db.core import DatabaseError, convert
from renus.db.models.base import Model
from renus.datastructures.id import ID, is_identity

_ID_NATIVE_TYPES: tuple[type, ...] = (int,)

try:
    from bson import (
        Binary,
        Code,
        DBRef,
        Decimal128,
        Int64,
        MaxKey,
        MinKey,
        ObjectId,
        Regex,
        Timestamp,
    )

    _BSON_TYPES: tuple[type, ...] = (
        ObjectId,
        Binary,
        Code,
        DBRef,
        Decimal128,
        Int64,
        MaxKey,
        MinKey,
        Regex,
        Timestamp,
    )
    _ID_NATIVE_TYPES = (int, ObjectId)
except ImportError:
    _BSON_TYPES = ()



class MongoDialect:
    """Describe MongoDB's type support and value encoding.

    A dialect encapsulates what the backend can store natively versus what the
    framework must translate. Values whose type BSON can represent are stored in
    their native form; everything else is encoded the way the framework
    serializes it elsewhere so it round-trips through repository coercion.
    """

    native_types: tuple[type, ...] = (
        bool,
        int,
        float,
        str,
        bytes,
        bytearray,
        datetime,
        dict,
        list,
        tuple,
        re.Pattern,
        *_BSON_TYPES,
    )

    def supports(self, value: Any) -> bool:
        """Return whether BSON can store ``value`` in its native form."""
        return isinstance(value, self.native_types)

    def encode_value(self, value: Any, field_meta: Any = None) -> Any:
        """Convert a value into something BSON can store using metadata if provided.

        ``dict``/``list``/``tuple``/``set`` are traversed so nested values are
        encoded too. Types BSON cannot represent (``UUID``, ``Decimal``,
        ``date``, ``time``) are converted according to field metadata or standard
        BSON forms.
        """
        if value is None:
            return None

        if hasattr(field_meta, "fields") and isinstance(value, dict):
            encoded_doc: dict[str, Any] = {}
            for k, v in value.items():
                if str(k).startswith("$"):
                    raise DatabaseError(f"{k}: key with $ not allowed")
                fmeta = field_meta.fields.get(k)
                encoded_doc[k] = self.encode_value(v, fmeta)
            return encoded_doc

        if isinstance(value, Model):
            return self.encode_value(dict(value), getattr(value, "__db_metadata__", field_meta))

        if isinstance(value, dict):
            target_model = getattr(field_meta, "target", None)
            nested_meta = getattr(target_model, "__db_metadata__", None) if target_model else None
            if nested_meta:
                r= {}
                for k, v in value.items():
                    if str(k).startswith("$"):
                        raise DatabaseError(f"{k}: key with $ not allowed")
                    r[k]=self.encode_value(v, nested_meta.fields.get(k))
                return r
            r= {}
            for k, v in value.items():
                if str(k).startswith("$"):
                    raise DatabaseError(f"{k}: key with $ not allowed")
                r[k]=self.encode_value(v)
            return r

        if isinstance(value, (list, tuple, set)):
            target_model = getattr(field_meta, "target", None)
            nested_meta = getattr(target_model, "__db_metadata__", None) if target_model else None
            return [self.encode_value(v, nested_meta) for v in value]

        target_type = getattr(field_meta, "inferred_type", None)

        if is_identity(target_type) or target_type is ID or isinstance(value, ID):
            if isinstance(value, ID):
                raw = value.value
                if raw is None:
                    return None
                if isinstance(raw, _ID_NATIVE_TYPES):
                    return raw
                return str(value)
            if value is not None and not isinstance(value, _ID_NATIVE_TYPES):
                return str(value)
            return value

        if target_type is UUID or isinstance(value, UUID):
            return str(value)

        if target_type is date or (isinstance(value, date) and not isinstance(value, datetime)):
            return value.isoformat()

        if target_type is time or isinstance(value, time):
            return value.isoformat()

        if target_type is Decimal or isinstance(value, Decimal):
            if isinstance(value, Decimal):
                if "Decimal128" in globals():
                    return Decimal128(value)
                return value
            if isinstance(value, (int, float, str)):
                return Decimal128(str(value)) if "Decimal128" in globals() else float(value)
            return value

        if target_type is bytes and isinstance(value, (bytes, bytearray)):
            return bytes(value)

        if self.supports(value):
            return value

        return str(value)

    def decode_value(self, value: Any, field_meta: Any = None) -> Any:
        native = self._decode_native(value)
        if native is None or field_meta is None:
            return native

        if hasattr(field_meta, "fields") and isinstance(native, dict):
            data = dict(native)
            for fname, fmeta in field_meta.fields.items():
                col = getattr(fmeta, "column_name", fname)
                if col in data:
                    val = data.pop(col) if col != fname else data[col]
                    data[fname] = self.decode_value(val, fmeta)
                elif fname in data:
                    val = data[fname]
                    data[fname] = self.decode_value(val, fmeta)
            return data

        target_type = getattr(field_meta, "inferred_type", field_meta)
        type_str = str(target_type).lower()

        if is_identity(target_type) or target_type is ID or "id" == type_str.rsplit(".", 1)[-1]:
            if isinstance(native, ID):
                return native
            return ID(native)

        if (target_type is bool or type_str in ("bool", "boolean")) and isinstance(native, int):
            return bool(native)

        if target_type is UUID or "uuid" in type_str:
            if isinstance(native, UUID):
                return native
            if isinstance(native, str):
                try:
                    return UUID(native)
                except Exception:
                    return native

        if target_type is date or type_str.rsplit(".", 1)[-1] == "date":
            if isinstance(native, date) and not isinstance(native, datetime):
                return native
            if isinstance(native, datetime):
                return native.date()
            if isinstance(native, str):
                try:
                    return date.fromisoformat(native)
                except Exception:
                    return native

        if target_type is time or type_str.rsplit(".", 1)[-1] == "time":
            if isinstance(native, time):
                return native
            if isinstance(native, str):
                try:
                    return time.fromisoformat(native)
                except Exception:
                    return native

        if target_type is datetime or type_str.rsplit(".", 1)[-1] == "datetime":
            if isinstance(native, datetime):
                if native.tzinfo is None:
                    return native.replace(tzinfo=timezone.utc)
                return native
            if isinstance(native, str):
                try:
                    dt = datetime.fromisoformat(native.rstrip("Z"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except Exception:
                    return native

        if target_type is Decimal or "decimal" in type_str:
            if isinstance(native, Decimal):
                return native
            if isinstance(native, (int, float, str)):
                try:
                    return Decimal(str(native))
                except Exception:
                    return native

        if target_type is bytes and isinstance(native, (bytes, bytearray)):
            return bytes(native)

        python_type = getattr(field_meta, "python_type", None)
        origin = getattr(python_type, "__origin__", None)
        args = getattr(python_type, "__args__", ())
        target_model = getattr(field_meta, "model_cls", None)
        if target_model is None:
            target_model = python_type if isinstance(python_type, type) else None
        if origin is list and args and isinstance(args[0], type):
            target_model = args[0]
        if target_model and hasattr(target_model, "__db_metadata__"):
            target_meta = getattr(target_model, "__db_metadata__")
            if isinstance(native, dict):
                return self.decode_value(native, target_meta)
            if isinstance(native, list):
                return [
                    self.decode_value(item, target_meta) if isinstance(item, dict) else item
                    for item in native
                ]

        return convert.decode_value(native, field_meta)

    def _decode_native(self, value: Any) -> Any:
        if not _BSON_TYPES:
            return value
        if isinstance(value, dict):
            return {k: self._decode_native(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._decode_native(v) for v in value]
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, Int64):
            return int(value)
        if isinstance(value, Decimal128):
            return value.to_decimal()
        if isinstance(value, Binary):
            return bytes(value)
        if isinstance(value, Timestamp):
            return value.as_datetime()
        return value
