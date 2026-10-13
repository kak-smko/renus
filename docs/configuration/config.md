# Config Module

Renus reads project settings from Python modules in a top-level `config` package. `Config` is a small accessor for one of those modules:

```python
from renus.config import Config

app_config = Config("app")  # imports config.app
```

The module name is resolved under `config`, so `Config("database")` imports `config.database`; dotted names are supported for nested modules as well. Place the package beside your application entry point and include `__init__.py` files where needed so Python can import it:

```text
my_project/
├── config/
│   ├── __init__.py
│   ├── app.py
│   └── database.py
└── main.py
```

Define settings as module-level variables in the usual case. Values are read from the imported Python module; Renus does not parse environment variables automatically. A module may also expose objects or mappings as values, but dotted-path lookup traverses attributes, not dictionary keys.

## Reading settings

Use `.get()` to retrieve a value with an optional fallback. Dotted paths traverse nested attributes:

```python
from renus.config import Config

app = Config("app")

debug = app.get("debug", False)
replica_uri = app.get("database.replica_uri")
```

`Config` also supports attribute access and dotted-path item access. For dotted traversal, use nested objects/attributes, not nested dictionaries:

```python
app.debug                    # top-level setting; raises AttributeError if absent
app["database.replica_uri"]  # raises KeyError if absent
```

The lookup methods traverse attributes, so for nested module settings use nested namespaces/objects, such as a module-level `database = SimpleNamespace(replica_uri=...)`. A plain nested dictionary is not traversed by dotted paths. `items()` returns the loaded module namespace as a mapping when possible; `snapshot()` returns a plain dictionary copy (or an empty dictionary when the loaded value is not mapping-like).

## Loading, missing modules, and caching

A `Config` object loads its named module when constructed. Successfully imported modules and missing-module results are cached by name for the process. If importing `config.<name>` fails, Renus logs a debug message and treats the config as empty; `.get()` then returns its default (or `None`), while attribute and item lookups raise their documented missing-value errors.

Because the cache is shared and a failed import is cached too, create the configuration module before starting the app. If you change configuration at runtime or need a test to reload it, clear or update `Config._cache` deliberately; there is no public reload method.

## Settings consumed by Renus

Renus does not enforce a single schema for config modules. The settings read by the framework depend on the feature in use. The current `app` settings include:

| Setting | Default | Used for |
| --- | --- | --- |
| `debug` | `False` | `App.debug` |
| `env` | `"local"` | `App.env` |
| `cacheDriver` | `"file"` | Default cache backend (`file` or `redis`) |
| `cache_file_path` | `"storage/cache/cache.sqlite"` | File-cache database path |
| `redis_host` | `"localhost"` | Redis cache host |
| `redis_port` | `6379` | Redis cache port |
| `redis_db` | `0` | Redis logical database |
| `redis_username`, `redis_password` | unset | Optional Redis credentials |
| `redis_ssl` | `False` | Enable Redis SSL |
| `redis_ssl_cert_reqs` | `"required"` | Redis SSL certificate requirement |
| `key` | `"123"` | Cache signing/encryption key; set a strong secret in production |
| `max_upload_size` | `50 * 1024 * 1024` | Maximum upload size in bytes |
| `max_body_size` | `10 * 1024 * 1024` | Maximum request body size in bytes |
| `max_headers` | `100` | Maximum request header count |
| `max_headers_size` | `8192` | Maximum size of an individual header |
| `max_cookies` | `50` | Maximum cookie count |
| `max_cookies_size` | `4096` | Maximum size of an individual cookie |
| `max_query_size` | `1024` | Maximum query-string size |
| `max_form_parts` | `1000` | Maximum number of form parts |
| `ipHeader` | `False` | Header to use for the request client IP when configured |
| `host` | unset | Base domain used to resolve request subdomains |
| `log_level` | `"INFO"` | Logger threshold |
| `log_path` | `"storage/logs"` | Log directory |
| `log_prefix` | logger default | Log-file prefix |
| `log_backup_days` | `30` | Daily log retention |
| `log_console` | `True` | Enable console logging |
| `log_rich` | `True` | Use the rich console handler when console logging is enabled |
| `log_json` | `False` | Use JSON log formatting |
| `log_format` | logger default | Text log format |
| `log_date_format` | logger default | Date format for text logs |
| `color` | terminal detection | Enable or disable ANSI color in Renus rich terminal styles |
| `admin_subdomain` | `"admin"` | Subdomain default used by the generated app route template |

Some request limits and terminal style settings are read when their modules are imported, so configure them before importing those Renus modules. See [Database Configuration](database.md) for database-specific settings and [Caching](../development/caching.md) for cache behavior.
