from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from renus.db.core import convert
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
        """Recursively convert a value into something BSON can store.

        ``dict``/``list``/``tuple``/``set`` are traversed so nested values are
        encoded too. Types BSON cannot represent (``UUID``, ``Decimal``,
        ``date``, ``time``) are converted to the string/number form the
        framework uses elsewhere. Any type outside the canonical catalogue is
        stored as its string form.
        """
        if value is None:
            return None
        if isinstance(value, Model):
            return self.encode_value(dict(value))
        if isinstance(value, dict):
            return {k: self.encode_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self.encode_value(v) for v in value]
        if self.supports(value):
            return value
        if isinstance(value, (date, time)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, ID):
            raw = value.value
            #raise RuntimeError(type(raw))
            if raw is None:
                return None
            if isinstance(raw, _ID_NATIVE_TYPES):
                return raw
            return str(value)
        return str(value)

    def decode_value(self, value: Any, field_meta: Any = None) -> Any:
        native = self._decode_native(value)
        if field_meta is None:
            return native
        if is_identity(field_meta.inferred_type):
            return ID(native) if native is not None else native
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
