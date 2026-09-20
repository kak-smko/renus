from __future__ import annotations

import json as _json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as _BinasciiError
from typing import Any, Callable

from renus.util.serialization import dumps

try:
    import orjson as _orjson
except ImportError:
    _orjson = None


class CodecError(RuntimeError):
    """Raised when decoding an encode64 value fails."""

def json_encode(
    value: Any,
    *,
    default: Callable[[Any], Any] | None = None,
    indent: bool = False,
) -> str:
    """Serialize a value to a JSON string, prefer-orjson when available.

    Parameters
    ----------
    value:
        Object to serialize.
    default:
        Callable invoked for values that are otherwise unserializable.
    indent:
        Whether to pretty-print with two-space indentation.
    """
    if _orjson is not None:
        option = _orjson.OPT_INDENT_2 if indent else 0
        try:
            return _orjson.dumps(value, default=default, option=option).decode("utf-8")
        except TypeError:
            pass
    return dumps(value)

def json_decode(
    text: "str | bytes | bytearray",
    *,
    decoder: Callable[[Any], Any] | None = None,
) -> Any:
    """Parse a JSON string or bytes into a Python object.

    Parameters
    ----------
    text:
        JSON payload to decode.
    decoder:
        Optional object hook applied to each JSON object.
    """
    if _orjson is not None and decoder is None:
        return _orjson.loads(text)
    if decoder is not None:
        return _json.loads(text, object_hook=decoder)
    return _json.loads(text)

def remove_pad64(text: str) -> str:
    """Return ``text`` with base64 padding removed.

    Parameters
    ----------
    text:
        Base64 string to strip ``"="`` padding from.
    """
    return text.replace("=", "")

def add_pad64(text: str) -> str:
    """Return ``text`` with base64 padding restored to a multiple of four.

    Parameters
    ----------
    text:
        Unpadded base64 string to normalize.
    """
    padding = -len(text) % 4
    return text if padding == 0 else text + "=" * padding

def encode64(value: Any) -> str:
    """Encode a value as a JSON string into a URL-safe unpadded base64 string.

    Parameters
    ----------
    value:
        Object to encode.
    """
    payload = json_encode(value).encode("utf-8")
    return remove_pad64(urlsafe_b64encode(payload).decode("ascii"))

def decode64(value: str, decoder: Callable[[Any], Any] | None = None) -> Any:
    """Decode an encode64 string back into a Python object.

    Parameters
    ----------
    value:
        encode64 string to decode.
    decoder:
        Optional object hook applied to each JSON object.
    """
    try:
        raw = urlsafe_b64decode(add_pad64(value))
    except (_BinasciiError, ValueError):
        raise CodecError("Invalid encode64 Format:" + str(value)) from None
    try:
        text = raw.decode("utf-8")
        return json_decode(text, decoder=decoder)
    except (UnicodeDecodeError, ValueError, TypeError):
        raise CodecError("Invalid encode64 Format:" + str(value)) from None
