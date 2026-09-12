from __future__ import annotations

import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Final, override

from renus.rich._style import _Style

__all__ = ["DailyFileHandler", "RichHandler"]

_DEFAULT_PREFIX: Final[str] = "renus"

_NAME_SUFFIX: Final[re.Pattern[str]] = re.compile(
    r"-(?P<day>\d{4}-\d{2}-\d{2})\.log$"
)

_RICH_DATE_FMT: Final[str] = "%Y-%m-%d %H:%M:%S"

_RICH_LEVEL_STYLES: Final[dict[int, _Style]] = {
    logging.DEBUG: _Style(2),
    logging.INFO: _Style(96),
    logging.WARNING: _Style(93),
    logging.ERROR: _Style(91),
    logging.CRITICAL: _Style(1, 91),
}

_RICH_DIM = _Style(2)

_RICH_FORMATTER = logging.Formatter()

class RichHandler(logging.Handler):
    """Handle logging output by rendering colored, styled lines."""

    def __init__(
        self,
        *,
        stream: IO[str] | None = None,
        level_styles: dict[int, _Style] | None = None,
        datefmt: str = _RICH_DATE_FMT,
        show_time: bool = True,
        show_level: bool = True,
        show_name: bool = True,
        level_width: int = 8,
    ) -> None:
        """Initialize the rich handler.

        Parameters
        ----------
        stream:
            Output stream. Defaults to ``sys.stderr``.
        level_styles:
            Mapping of level numbers to styles. Defaults to the built-in set.
        datefmt:
            Timestamp format string.
        show_time:
            Whether to render the timestamp.
        show_level:
            Whether to render the level name.
        show_name:
            Whether to render the logger name.
        level_width:
            Fixed width used to pad level names.
        """
        super().__init__()
        self._stream = stream if stream is not None else sys.stderr
        self._level_styles = (
            level_styles if level_styles is not None else dict(_RICH_LEVEL_STYLES)
        )
        self._datefmt = datefmt
        self._show_time = show_time
        self._show_level = show_level
        self._show_name = show_name
        self._level_width = level_width

    def emit(self, record: logging.LogRecord) -> None:
        """Write a formatted log record to the stream."""
        try:
            self._stream.write(self._line(record) + "\n")
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

    def _line(self, record: logging.LogRecord) -> str:
        style = self._level_styles.get(record.levelno, _Style())
        parts: list[str] = []
        if self._show_time:
            when = datetime.fromtimestamp(record.created).strftime(self._datefmt)
            parts.append(_RICH_DIM(when) + " ")
        if self._show_level:
            parts.append(style(record.levelname.ljust(self._level_width)) + " ")
        if self._show_name:
            parts.append(_RICH_DIM(record.name) + " ")
        parts.append(style(record.getMessage()))
        if record.exc_info:
            parts.append("\n" + style(_RICH_FORMATTER.formatException(record.exc_info)))
        if record.stack_info:
            parts.append("\n" + style(_RICH_FORMATTER.formatStack(record.stack_info)))
        return "".join(parts)

    def flush(self) -> None:
        """Flush any buffered output to the stream."""
        self._stream.flush()

class DailyFileHandler(logging.Handler):
    """Handle logging output into per-day rotated files."""

    _directory: Path
    _prefix: str
    _keep_days: int
    _encoding: str
    _utc: bool
    _active_day: str | None
    _stream: IO[str] | None

    def __init__(
        self,
        directory: str | Path,
        prefix: str = _DEFAULT_PREFIX,
        *,
        keep_days: int = 30,
        encoding: str = "utf-8",
        utc: bool = True,
    ) -> None:
        """Initialize the daily file handler.

        Parameters
        ----------
        directory:
            Directory in which log files are written.
        prefix:
            File name prefix. Defaults to ``"renus"``.
        keep_days:
            Number of days to retain log files.
        encoding:
            File encoding used when writing logs.
        utc:
            Whether dates are computed in UTC rather than local time.
        """
        super().__init__()
        self._directory = Path(directory)
        self._prefix = prefix
        self._keep_days = max(1, keep_days)
        self._encoding = encoding
        self._utc = utc
        self._active_day = None
        self._stream = None
        self._directory.mkdir(parents=True, exist_ok=True)
        self._purge_expired()

    def _today(self) -> str:
        now = datetime.now(timezone.utc if self._utc else None)
        return now.date().isoformat()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc if self._utc else None)

    def _path_for(self, day: str) -> Path:
        return self._directory / f"{self._prefix}-{day}.log"

    def _purge_expired(self) -> None:
        cutoff = self._now().date()
        retention = timedelta(days=self._keep_days)
        for entry in self._directory.glob(f"{self._prefix}-*.log"):
            match = _NAME_SUFFIX.search(entry.name)
            if not match:
                continue
            try:
                day = datetime.strptime(match["day"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if (cutoff - day) > retention:
                try:
                    entry.unlink()
                except OSError:
                    pass

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Write a record to today's log file."""
        today = self._today()
        if today != self._active_day:
            self._rollover(today)
        stream = self._stream
        if stream is None:

            self.handleError(record)
            return
        try:
            stream.write(self.format(record) + "\n")
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

    def _rollover(self, day: str) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        self._active_day = day
        try:
            self._stream = open(
                self._path_for(day), "a", encoding=self._encoding,
                errors="backslashreplace",
            )
        except OSError:
            self._active_day = None

    @override
    def flush(self) -> None:
        """Flush any buffered output to the active file."""
        if self._stream is not None:
            self._stream.flush()

    @override
    def close(self) -> None:
        """Flush and close the active log file."""
        self.acquire()
        try:
            try:
                if self._stream is not None:
                    self.flush()
                    self._stream.close()
                    self._stream = None
            finally:
                self.release()
        finally:
            super().close()
