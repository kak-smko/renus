import io
import json
import logging
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from renus.log import Log, RichHandler
from renus.log.logger import DailyFileHandler, configure, get_logger
from renus.rich import _style as style_mod

@pytest.fixture(autouse=True)
def reset_log_state():
    Log.reset()
    yield
    Log.reset()

_DEFAULT_SETTINGS = {
    "log_path": "storage/logs",
    "log_prefix": "renus",
    "log_level": "INFO",
    "log_backup_days": 30,
    "log_console": False,
    "log_json": False,
}

@pytest.fixture
def log_cfg(tmp_path):
    overrides = {}

    def fake_get(key, default=None):
        if key in overrides:
            return overrides[key]
        return _DEFAULT_SETTINGS.get(key, default)

    def set_override(**kwargs):
        overrides.update(kwargs)

    set_override(log_path=str(tmp_path / "logs"))
    with patch("renus.log.logger.Config.get", side_effect=fake_get):
        yield set_override

def _file_handler():
    return next(
        h for h in Log().logger.handlers if isinstance(h, DailyFileHandler)
    )

def _log_files(directory):
    return list(directory.glob("renus-*.log"))

class TestConfigure:
    def test_attaches_file_handler(self, log_cfg):
        configure(reset=True)
        assert any(isinstance(h, DailyFileHandler) for h in Log().logger.handlers)

    def test_only_console_handler_when_console_enabled(self, log_cfg):
        log_cfg(log_console=True)
        configure(reset=True)
        handlers = Log().logger.handlers
        assert sum(1 for h in handlers if isinstance(h, DailyFileHandler)) == 1
        assert sum(1 for h in handlers if not isinstance(h, DailyFileHandler)) == 1

    def test_is_idempotent_no_duplicate_file_handlers(self, log_cfg):
        configure(reset=True)
        configure(reset=True)
        handlers = Log().logger.handlers
        file_handlers = sum(1 for h in handlers if isinstance(h, DailyFileHandler))
        assert file_handlers == 1

    def test_reset_clears_handlers(self, log_cfg):
        configure(reset=True)
        root = Log().logger
        assert root.handlers
        Log.reset()
        assert root.handlers == []
        assert Log._configured is False

    def test_get_logger_is_wired_to_file_handler(self, log_cfg, tmp_path):
        logger = get_logger("renus.sub")
        logger.info("via get_logger")
        files = _log_files(tmp_path / "logs")
        assert files
        assert "via get_logger" in files[0].read_text()

class TestDailyFileBehaviour:
    def test_writes_records_to_todays_file(self, log_cfg, tmp_path):
        configure(reset=True)
        Log().info("first")
        Log().info("second")
        files = _log_files(tmp_path / "logs")
        assert len(files) == 1
        content = files[0].read_text()
        assert "first" in content
        assert "second" in content

    def test_creates_missing_directory(self, log_cfg, tmp_path):
        log_cfg(log_path=str(tmp_path / "deep" / "nested" / "logs"))
        configure(reset=True)
        assert (tmp_path / "deep" / "nested" / "logs").is_dir()

    def test_rotates_to_new_file_on_day_change(self, log_cfg, tmp_path):
        configure(reset=True)
        handle = _file_handler()
        handle._today = lambda: "2026-09-01"
        Log().info("day1")
        handle._today = lambda: "2026-09-02"
        Log().info("day2")

        day1 = tmp_path / "logs" / "renus-2026-09-01.log"
        day2 = tmp_path / "logs" / "renus-2026-09-02.log"
        assert day1.exists() and "day1" in day1.read_text()
        assert day2.exists() and "day2" in day2.read_text()

    def test_purge_expired_files(self, log_cfg, tmp_path):
        configure(reset=True)
        handle = _file_handler()
        handle._now = lambda: datetime(2026, 9, 2, tzinfo=timezone.utc)
        (tmp_path / "logs" / "renus-2026-08-01.log").write_text("old")
        (tmp_path / "logs" / "renus-2026-08-10.log").write_text("ok")
        (tmp_path / "logs" / "renus-random.log").write_text("non-date")
        handle._purge_expired()

        assert not (tmp_path / "logs" / "renus-2026-08-01.log").exists()
        assert (tmp_path / "logs" / "renus-2026-08-10.log").exists()
        assert (tmp_path / "logs" / "renus-random.log").exists()

    def test_keep_days_is_at_least_one(self, log_cfg):
        log_cfg(log_backup_days=0)
        configure(reset=True)
        assert _file_handler()._keep_days == 1

class TestLogFacade:
    def test_info_writes_to_log_file(self, log_cfg, tmp_path):
        configure(reset=True)
        Log().info("hello world")
        files = _log_files(tmp_path / "logs")
        assert files
        assert "hello world" in files[0].read_text()

    def test_debug_suppressed_at_info_level(self, log_cfg, tmp_path):
        configure(reset=True)
        Log().debug("hidden")
        assert not _log_files(tmp_path / "logs")

    def test_debug_emitted_when_debug_level(self, log_cfg, tmp_path):
        log_cfg(log_level="DEBUG")
        configure(reset=True)
        Log().debug("visible")
        files = _log_files(tmp_path / "logs")
        assert files
        assert "visible" in files[0].read_text()

    def test_json_logging(self, log_cfg, tmp_path):
        log_cfg(log_json=True)
        configure(reset=True)
        Log().info("json hello", extra={"request_id": 5})
        files = _log_files(tmp_path / "logs")
        assert files
        data = json.loads(files[0].read_text().strip().splitlines()[0])
        assert data["level"] == "INFO"
        assert data["message"] == "json hello"
        assert data["extra"] == {"request_id": 5}

    def test_json_exception_lowered_to_string(self, log_cfg, tmp_path):
        log_cfg(log_json=True)
        configure(reset=True)
        try:
            raise ValueError("boom")
        except ValueError:
            Log().exception("err")
        files = _log_files(tmp_path / "logs")
        assert files
        data = json.loads(files[0].read_text().strip().splitlines()[0])
        assert "boom" in data["exception"]
        assert data["level"] == "ERROR"

    def test_json_always_serialisable(self, log_cfg, tmp_path):
        log_cfg(log_json=True)
        configure(reset=True)
        Log().info("bytes", extra={"binary": b"\x00\xff"})
        files = _log_files(tmp_path / "logs")
        assert files
        json.loads(files[0].read_text().strip().splitlines()[0])

    @pytest.mark.parametrize(
        "method", ["debug", "info", "warning", "error", "critical", "exception"]
    )
    def test_level_methods_delegate_to_underlying(self, log_cfg, method):
        configure(reset=True)
        log = Log()
        with patch.object(log.logger, method) as mocked:
            getattr(log, method)("msg %s", "arg", exc_info=False)
            mocked.assert_called_once_with("msg %s", "arg", exc_info=False)

    def test_instances_share_the_same_underlying_logger(self, log_cfg):
        configure(reset=True)
        first = Log("renus").logger
        second = Log("renus").logger
        assert first is second

@pytest.fixture
def force_color():
    original = style_mod.color_enabled
    style_mod.color_enabled = True
    yield
    style_mod.color_enabled = original

class TestRichHandler:
    def test_line_contains_time_level_name_and_message(self):
        buffer = io.StringIO()
        h = RichHandler(stream=buffer)
        lg = _logger_for(h)
        lg.warning("hello %s", "world")
        out = buffer.getvalue()
        assert "hello world" in out
        assert "WARNING" in out
        assert "renus.rich" in out

    def test_level_is_padded(self):
        buffer = io.StringIO()
        h = RichHandler(stream=buffer)
        lg = _logger_for(h)
        lg.info("msg")
        assert "INFO    " in buffer.getvalue().splitlines()[0]

    def test_level_width_is_configurable(self):
        buffer = io.StringIO()
        h = RichHandler(stream=buffer, level_width=6)
        lg = _logger_for(h)
        lg.info("msg")
        assert "INFO  " in buffer.getvalue().splitlines()[0]

    def test_components_can_be_hidden(self):
        buffer = io.StringIO()
        h = RichHandler(
            stream=buffer, show_time=False, show_name=False, show_level=False
        )
        _logger_for(h).info("bare")
        assert buffer.getvalue().strip() == "bare"

    def test_message_styled_by_level(self, force_color):
        buffer = io.StringIO()
        h = RichHandler(stream=buffer)
        lg = _logger_for(h, level=logging.WARNING)
        lg.warning("warn")
        lg.error("err")
        out = buffer.getvalue()
        assert "\x1b[93m" in out
        assert "\x1b[91m" in out

    def test_setlevel_filters_records(self):
        buffer = io.StringIO()
        h = RichHandler(stream=buffer)
        h.setLevel(logging.ERROR)
        lg = _logger_for(h)
        lg.warning("skipped")
        lg.error("kept")
        out = buffer.getvalue()
        assert "skipped" not in out
        assert "kept" in out

    def test_default_stream_is_stderr(self):
        h = RichHandler(show_level=False, show_name=False, show_time=False)
        assert h._stream is __import__("sys").stderr

    def test_exception_is_included(self):
        buffer = io.StringIO()
        h = RichHandler(stream=buffer)
        lg = _logger_for(h)
        try:
            raise ValueError("boom")
        except ValueError:
            lg.exception("failed")
        assert "boom" in buffer.getvalue()

    def test_plain_when_color_disabled(self):
        buffer = io.StringIO()
        h = RichHandler(stream=buffer)
        lg = _logger_for(h)
        lg.error("err")
        assert "\x1b[" not in buffer.getvalue()

class TestLogRich:

    def test_rich_console_when_enabled(self, log_cfg):
        log_cfg(log_console=True, log_rich=True)
        configure(reset=True)
        assert any(isinstance(h, RichHandler) for h in Log().logger.handlers)
        assert any(isinstance(h, DailyFileHandler) for h in Log().logger.handlers)

    def test_plain_stream_when_disabled(self, log_cfg):
        log_cfg(log_console=True, log_rich=False)
        configure(reset=True)
        assert not any(isinstance(h, RichHandler) for h in Log().logger.handlers)
        assert any(isinstance(h, DailyFileHandler) for h in Log().logger.handlers)

def _logger_for(handler, level=logging.DEBUG):
    logger = logging.getLogger("renus.rich_test")
    logger.setLevel(level)
    logger.handlers[:] = [handler]
    logger.propagate = False
    return logger
