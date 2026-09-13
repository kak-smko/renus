# Logging

Renus includes a small logging layer built on the standard library's `logging` module. It writes to a colored terminal handler and to per-day rotated files, and can emit structured JSON when needed. It is used throughout Renus itself — the cache, scheduling, database validation, and error responses all log through it.

Everything lives in `renus.log` and is exported from the `renus.log` package:

```python
from renus.log import Log, configure, get_logger, DailyFileHandler, RichHandler, JsonFormatter
```

## Auto-configuration

The `renus` logger is configured **lazily**: the first time you use `Log()` or `get_logger()`, Renus reads the `app` config and attaches its handlers. There is no required setup step.

```python
from renus.log import Log

Log().info("Application started")
```

You can also configure explicitly with `configure(reset=True)`, and tear everything down with `Log.reset()`:

```python
from renus.log import configure, Log

configure(reset=True)   # build handlers from current config
# ... run ...
Log.reset()             # close and remove all renus handlers
```

By default two handlers are attached:

- a **console** handler writing colored, styled lines to `stderr` (`RichHandler`), and
- a **file** handler writing to daily-rotated log files (`DailyFileHandler`).

No propagation is set on the root `renus` logger, so records are not duplicated up the hierarchy.

## The `Log` facade

`Log` is a thin facade over a configured `logging.Logger`. It is the recommended way to log from application code.

```python
from renus.log import Log

log = Log()                 # namespace defaults to "renus"
log.debug("verbose detail")
log.info("started worker %s", worker_id)
log.warning("disk space low: %s", free_bytes)
log.error("request failed: %s", exc)
log.critical("service shutting down")

try:
    ...
except Exception:
    log.exception("failed to process order")  # logs with traceback at ERROR level
```

Each method delegates to the matching method on the underlying logger, so standard `logging` keyword arguments such as `extra={...}` are supported.

### Namespaces

Pass a namespace to `Log` (or use `get_logger`) to tag your records:

```python
from renus.log import Log, get_logger

Log("payments").info("charge succeeded")   # name="payments"
logger = get_logger("payments.billing")    # a configured logging.Logger
```

All `Log()` instances and namespaces share the same configured handlers but keep distinct logger names, so the name appears in each formatted line.

## Configuration keys

Logging is configured from the `app` config module. All keys are optional.

| Config key       | Default                    | Description |
| ---------------- | -------------------------- | ----------- |
| `log_level`      | `"INFO"`                   | Threshold level. Accepts `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `NOTSET`, or a numeric `logging` level. |
| `log_path`       | `"storage/logs"`           | Directory where daily log files are written (created automatically). |
| `log_prefix`     | `"renus"`                  | File name prefix for daily files. |
| `log_backup_days`| `30`                       | Days of log files to retain. Files older than this are deleted. |
| `log_console`    | `True`                     | Enable the console handler (`stderr`). |
| `log_rich`       | `True`                     | Use the styled `RichHandler` for the console. When `False`, a plain `logging.StreamHandler` is used. |
| `log_json`       | `False`                    | Emit records as JSON instead of line-oriented text. |
| `log_format`     | see below                  | `printf`-style format string for text output. |
| `log_date_format`| `"%Y-%m-%d %H:%M:%S"`      | Timestamp format used in text output. |

The default text format is:

```
[%(asctime)s] %(levelname)-7s %(name)s | %(message)s
```

Example config:

```python
# config/app.py
log_level = "DEBUG"
log_path = "var/logs"
log_prefix = "myapp"
log_backup_days = 14
log_rich = False
```

See [Config](/docs/configuration/config.md) for how to set config values.

## Daily file rotation

The `DailyFileHandler` writes to a single file per day, named `{prefix}-{date}.log` (e.g. `renus-2026-09-01.log`). Dates are computed in UTC by default. When the day rolls over, the handler closes the previous file and opens the new one (see `_rollover`).

On initialization (and each new file), files older than `log_backup_days` are removed. Files that do not match the `-YYYY-MM-DD.log` suffix are left alone. The retention count is clamped to at least `1`.

The log directory is created recursively if it does not exist.

## JSON output

Set `log_json = True` to have records serialized as JSON one-per-line by `JsonFormatter`:

```python
log_cfg(log_json=True)
configure(reset=True)
Log().info("charge succeeded", extra={"amount": 9.99, "request_id": 5})
```

Each JSON object contains:

| Field       | Description |
| ----------- | ----------- |
| `time`      | Timestamp formatted with the date format. |
| `level`     | Level name (e.g. `INFO`). |
| `name`      | Logger name / namespace. |
| `message`   | The formatted log message. |
| `extra`     | Any non-reserved `extra` values passed to the logging call. Present only when there are extras. |
| `exception` | Exception traceback, when one is set (e.g. via `exception()`). |
| `stack`     | Stack information, when recorded. |

Extra values are forced to a JSON-serializable form, so values that are not natively JSON-encodable (such as `bytes`) are converted rather than raising.

## Using the handlers directly

`DailyFileHandler` and `RichHandler` are exported for advanced use, and can be attached to any logger:

```python
from renus.log import DailyFileHandler

handler = DailyFileHandler("logs", prefix="app", keep_days=7, utc=True)
```



| Handler            | Purpose |
| ------------------ | ------- |
| `RichHandler`      | Renders colored, styled console output to `stderr`. Levels are styled (e.g. `INFO` in cyan, `ERROR` in red) via `renus.rich`; the timestamps and logger name are dimmed. |
| `DailyFileHandler` | Writes per-day rotated files, purging expired files. |
| `JsonFormatter`    | Formats records as JSON objects. |
