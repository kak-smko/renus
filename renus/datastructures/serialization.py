from __future__ import annotations

import datetime
import decimal
import json
import math
import re
import uuid
from collections.abc import Mapping
from typing import Any

from renus.db.models.id import ID

try:
    import orjson as _orjson
except ImportError:
    _orjson = None

__all__ = ["jsonEncoder", "JSONEncoder", "json_decoder", "dumps", "loads", "dumps_bytes"]


_ISOFORMAT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_UUID_RE = re.compile(
    r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-"
    r"[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$"
)
_DECIMAL_RE = re.compile(r"^-?\d+\.\d+$")
_ID_PREFIX = "id:"

class jsonEncoder(json.JSONEncoder):
    """JSON encoder with renus-specific default value handling."""

    def default(self, o: Any) -> Any:
        """Encode the object using renus's default value rules."""
        return _encode_default_value(o)

JSONEncoder = jsonEncoder

def _encode_datetime(value: datetime.datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(datetime.timezone.utc)
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        base += f".{value.microsecond:06d}"
    return base + "Z"

def _encode_default_value(o: Any) -> Any:
    if isinstance(o, datetime.datetime):
        return _encode_datetime(o)
    if isinstance(o, datetime.date):
        return o.isoformat() + "T00:00:00Z"
    if isinstance(o, datetime.time):
        encoded = o.isoformat()
        return encoded[:8] if o.microsecond == 0 else encoded
    if isinstance(o, ID):
        return f"{_ID_PREFIX}{o}"
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, decimal.Decimal):
        return str(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=repr)
    if isinstance(o, (str, int, float, bool, type(None))):
        return o
    if isinstance(o, Mapping):
        return dict(o)
    if hasattr(o, "__dict__"):
        return dict(vars(o))
    return str(o)

def json_decoder(value: Any) -> Any:
    """Decode serialized values back into renus-native objects."""
    if isinstance(value, dict):
        return {k: json_decoder(v) for k, v in value.items()}
    if isinstance(value, str) and value.startswith(_ID_PREFIX):
        return ID(value[len(_ID_PREFIX):])
    if isinstance(value, list):
        return [json_decoder(item) for item in value]
    if isinstance(value, str) and value:
        return _decode_string(value)
    return value

def _decode_string(value: str) -> Any:
    length = len(value)

    if length >= 19 and _ISOFORMAT_RE.match(value):
        try:
            clean = value.rstrip("Z")
            return datetime.datetime.fromisoformat(clean)
        except (ValueError, TypeError):
            pass

    if length == 36 and _UUID_RE.match(value):
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError):
            pass

    if length >= 3 and _DECIMAL_RE.match(value):
        try:
            return decimal.Decimal(value)
        except (decimal.InvalidOperation, ValueError):
            pass

    return value

def dumps(
    obj: Any, *, separators: tuple[str, str] = (",", ":"), **kwargs: Any
) -> str:
    """Serialize an object to a compact JSON string."""
    return json.dumps(
        obj,
        cls=jsonEncoder,
        ensure_ascii=False,
        allow_nan=True,
        separators=separators,
        **kwargs,
    )

def _orjson_prepare(o: Any, holder: dict) -> Any:
    t = type(o)
    if t is dict:
        rebuilt = None
        for k, v in o.items():
            nv = _orjson_prepare(v, holder)
            if nv is not v:
                if rebuilt is None:
                    rebuilt = dict(o)
                rebuilt[k] = nv
        return o if rebuilt is None else rebuilt
    if t is list:
        rebuilt = None
        for i, v in enumerate(o):
            nv = _orjson_prepare(v, holder)
            if nv is not v:
                if rebuilt is None:
                    rebuilt = list(o)
                rebuilt[i] = nv
        return o if rebuilt is None else rebuilt
    if t is tuple:
        return tuple(_orjson_prepare(v, holder) for v in o)
    if isinstance(o, float):
        if not math.isfinite(o):
            holder["value"] = True
        return o
    if type(o) in (str, int, bool):
        return o
    return _encode_default_value(o)

def dumps_bytes(obj: Any) -> bytes:
    """Serialize an object to UTF-8 JSON bytes."""
    if _orjson is not None:
        holder = {"value": False}
        try:
            prepared = _orjson_prepare(obj, holder)
        except (RecursionError, ValueError):
            prepared = obj
            holder["value"] = True
        if not holder["value"]:
            try:
                return _orjson.dumps(prepared)
            except TypeError:
                pass
    return json.dumps(
        obj,
        cls=jsonEncoder,
        ensure_ascii=False,
        allow_nan=True,
        separators=(",", ":"),
    ).encode("utf-8")

def loads(text: "str | bytes | bytearray", **kwargs: Any) -> Any:
    """Deserialize a JSON string into renus-native objects."""
    kwargs.setdefault("object_hook", json_decoder)
    return json.loads(text, **kwargs)
