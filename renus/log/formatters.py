from __future__ import annotations

import logging
from typing import Any, Final, override

from renus.util.codec import json_encode


_TXT_FORMAT: Final[str] = (
    "[%(asctime)s] %(levelname)-7s %(name)s | %(message)s"
)

_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

class JsonFormatter(logging.Formatter):
    """Format log records as JSON objects."""

    _RESERVED: Final[frozenset[str]] = frozenset(
        logging.LogRecord("", 0, "", 0, "", "", (), None).__dict__
    )

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Serialize a record to a JSON string."""
        payload: dict[str, Any] = {
            "time": self.formatTime(record, _DATE_FORMAT),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self._RESERVED and key not in payload
        }
        if extra:
            payload["extra"] = extra
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = record.stack_info
        return json_encode(payload, default=str)
