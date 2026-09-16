from __future__ import annotations

import base64
import datetime
import json
import uuid
from collections.abc import Iterator
from decimal import Decimal
from enum import Enum
from typing import Any

from renus.db.models.id import ID


__all__ = [
    "BackupEncoder",
    "BackupFileWriter",
    "DEFAULT_PAGE_SIZE",
    "backup_decode_hook",
    "backup_encode",
    "dump_rows",
    "load_rows",
    "load_rows_pages",
]

DEFAULT_PAGE_SIZE = 1000

_READ_CHUNK_SIZE = 1 << 20

def backup_encode(value: Any) -> Any:
    """Encode a value into a portable JSON-safe representation."""
    if isinstance(value, datetime.datetime):
        iso = value.isoformat()
        return {"$date": iso + "Z" if value.tzinfo is None else iso}
    if isinstance(value, datetime.date):
        return {"$date": value.isoformat()}
    if isinstance(value, datetime.time):
        return {"$time": value.isoformat()}
    if isinstance(value, uuid.UUID):
        return {"$uuid": str(value)}
    if isinstance(value, Decimal):
        return {"$numberDecimal": str(value)}
    if isinstance(value, Enum):
        return {"$enum": value.value}
    if isinstance(value, ID):
        return {"$id": str(value)}
    if isinstance(value, (bytes, bytearray)):
        return {
            "$binary": {
                "base64": base64.b64encode(bytes(value)).decode("ascii"),
                "subType": "00",
            }
        }
    if isinstance(value, dict):
        return {str(k): backup_encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [backup_encode(v) for v in value]

    try:
        json.dumps(value)
    except (TypeError, ValueError):
        raise TypeError(
            f"Value of type {type(value).__name__} is not portable-safe for backup: {value!r}"
        )
    return value

def backup_decode_hook(obj: Any) -> Any:
    """Decode a previously encoded value back into its native type."""
    if not isinstance(obj, dict):
        return obj

    if "$date" in obj:
        val = obj["$date"]
        try:
            return datetime.datetime.fromisoformat(str(val).rstrip("Z"))
        except (ValueError, TypeError):
            return val
    if "$time" in obj:
        try:
            return datetime.time.fromisoformat(str(obj["$time"]))
        except (ValueError, TypeError):
            return obj["$time"]
    if "$uuid" in obj:
        try:
            return uuid.UUID(obj["$uuid"])
        except (ValueError, TypeError, AttributeError):
            return obj["$uuid"]

    if "$id" in obj:
        try:
            return ID(obj["$id"])
        except (ValueError, TypeError, AttributeError):
            return obj["$id"]

   
    if "$numberDecimal" in obj:
        try:
            return Decimal(str(obj["$numberDecimal"]))
        except Exception:
            return obj["$numberDecimal"]
    if "$enum" in obj:
        return obj["$enum"]
    if "$binary" in obj:
        raw = obj["$binary"]
        try:
            return base64.b64decode(raw["base64"])
        except Exception:
            return raw

    return obj

class BackupEncoder(json.JSONEncoder):
    """JSON encoder that serializes portable backup types."""

    def default(self, o: Any) -> Any:
        """Encode a non-standard object using the backup encoder."""
        return backup_encode(o)

def dump_rows(rows: list[dict[str, Any]], *, indent: int = 2) -> str:
    """Serialize a list of rows to portable backup JSON text."""
    return json.dumps(rows, cls=BackupEncoder, indent=indent)

def load_rows(json_text: str) -> list[dict[str, Any]]:
    """Deserialize backup JSON text into a list of rows."""
    data = json.loads(json_text, object_hook=backup_decode_hook)
    if isinstance(data, dict):
        data = [data]
    return data

class BackupFileWriter:
    """Streams rows to a backup file as a JSON array."""

    def __init__(self, fileobj: Any) -> None:
        """Initialize the writer for the given file object.

        Parameters
        ----------
        fileobj:
            Open binary or text file object to write backup rows to.
        """
        self._file = fileobj
        self._count = 0
        self._write("[")

    def _write(self, text: str) -> None:
        self._file.write(text)

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        """Write the given rows to the backup file."""
        for row in rows:
            if not row:
                continue
            if self._count > 0:
                self._write(",")
            self._write(json.dumps(backup_encode(row), cls=BackupEncoder))
            self._count += 1

    def finish(self) -> None:
        """Close the JSON array and complete the backup file."""
        self._write("]")

def _extract_rows(decoder: json.JSONDecoder, buffer: str) -> tuple[str, list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    pos = 0
    n = len(buffer)
    while True:
        while pos < n and buffer[pos] in " \t\r\n":
            pos += 1
        if pos >= n:

            return buffer[pos:], rows, False
        ch = buffer[pos]
        if ch == "]":
            return buffer[pos + 1 :], rows, True
        if ch == ",":
            pos += 1
            continue
        try:
            value, end = decoder.raw_decode(buffer, pos)
        except json.JSONDecodeError:

            return buffer[pos:], rows, False
        rows.append(value)
        pos = end

def load_rows_pages(fileobj: Any, batch_size: int = DEFAULT_PAGE_SIZE) -> Iterator[list[dict[str, Any]]]:
    """Yield rows from a backup file in batches of the given size."""
    decoder = json.JSONDecoder(object_hook=backup_decode_hook)
    buffer = ""
    started = False

    def pump() -> bool:
        nonlocal buffer
        chunk = fileobj.read(_READ_CHUNK_SIZE)
        buffer += chunk
        return bool(chunk)

    while not started:
        stripped = buffer.lstrip()
        if stripped and stripped[0] == "[":
            buffer = buffer[buffer.find("[") + 1 :]
            started = True
        elif not pump():
            break

    if not started:

        data = json.loads(buffer or "{}", object_hook=backup_decode_hook)
        if isinstance(data, dict):
            data = [data]
        elif data is None:
            return
        if data:
            yield list(data)
        return

    page: list[dict[str, Any]] = []
    while True:
        buffer, rows, finished = _extract_rows(decoder, buffer)
        for row in rows:
            page.append(row)
            if len(page) >= batch_size:
                yield page
                page = []
        if finished:
            break
        if not pump():

            buffer, rows, finished = _extract_rows(decoder, buffer)
            for row in rows:
                page.append(row)
                if len(page) >= batch_size:
                    yield page
                    page = []
            break

    if page:
        yield page
