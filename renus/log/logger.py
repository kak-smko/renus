from __future__ import annotations

import logging
import os
import sys
from typing import Any, ClassVar, Final

from renus.config import Config

from .formatters import _DATE_FORMAT, _TXT_FORMAT, JsonFormatter
from .handlers import _DEFAULT_PREFIX, DailyFileHandler, RichHandler



_DEFAULT_LEVEL: Final[str] = "INFO"

_LEVELS: Final[dict[str, int]] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}

def _resolve_level(value: Any, default: int = logging.INFO) -> int:
    if isinstance(value, int):
        return value
    return _LEVELS.get(str(value).upper(), default)

def _load_settings() -> dict[str, Any]:
    app = Config("app")

    return {
        "level": app.get("log_level", _DEFAULT_LEVEL),
        "directory": os.path.abspath(app.get("log_path", "storage/logs")),
        "prefix": app.get("log_prefix", _DEFAULT_PREFIX),
        "keep_days": app.get("log_backup_days", 30),
        "console": app.get("log_console", True),
        "rich": app.get("log_rich", True),
        "json": app.get("log_json", False),
        "format": app.get("log_format", _TXT_FORMAT),
        "datefmt": app.get("log_date_format", _DATE_FORMAT),
    }

def _apply_settings(settings: dict[str, Any], *, reset: bool) -> None:
    logger = logging.getLogger("renus")
    if reset:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
    if not logger.handlers:
        formatter: logging.Formatter
        if settings["json"]:
            formatter = JsonFormatter()
        else:
            formatter = logging.Formatter(
                settings["format"], datefmt=settings["datefmt"]
            )

        if settings["console"]:
            if settings["rich"]:

                console: logging.Handler = RichHandler()
            else:
                stream_handler = logging.StreamHandler(sys.stderr)
                stream_handler.setFormatter(formatter)
                console = stream_handler
            logger.addHandler(console)

        file_handler = DailyFileHandler(
            settings["directory"],
            prefix=settings["prefix"],
            keep_days=settings["keep_days"],
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.setLevel(_resolve_level(settings["level"], logging.INFO))
    logger.propagate = False

def configure(*, reset: bool = True) -> None:
    """Configure the ``renus`` logger from application settings.

    Parameters
    ----------
    reset:
        Whether to remove and close existing handlers before configuring.
    """
    settings = _load_settings()
    _apply_settings(settings, reset=reset)
    Log._configured = True

def get_logger(namespace: str) -> logging.Logger:
    """Return a configured logger for the given namespace."""
    logger = logging.getLogger(namespace)
    Log._ensure_configured()
    return logger

class Log:
    """Facade exposing typed logging helpers for a namespace."""

    _configured: ClassVar[bool] = False
    _logger: logging.Logger

    def __init__(self, namespace: str = "renus") -> None:
        """Initialize a Log facade.

        Parameters
        ----------
        namespace:
            Logger namespace. Defaults to ``"renus"``.
        """
        self._logger = logging.getLogger(namespace)
        Log._ensure_configured()

    @classmethod
    def _ensure_configured(cls) -> None:
        if cls._configured:
            return

        _apply_settings(_load_settings(), reset=True)
        cls._configured = True

    @classmethod
    def reset(cls) -> None:
        """Remove and close all ``renus`` logger handlers."""
        logger = logging.getLogger("renus")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        cls._configured = False

    @property
    def logger(self) -> logging.Logger:
        """Return the underlying configured logger."""
        return self._logger

    def debug(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log a debug-level message."""
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log an info-level message."""
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log a warning-level message."""
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log an error-level message."""
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log a critical-level message."""
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg: object, *args: object, **kwargs: Any) -> None:
        """Log an exception with traceback at error level."""
        self._logger.exception(msg, *args, **kwargs)
