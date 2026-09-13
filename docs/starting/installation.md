# Installation

This page walks you through installing **Renus** on your machine so you can start building async web services.

## Requirements

Renus requires:

- **Python 3.10 or higher**
- **pip** (Python's package installer)

Renus supports any Python environment that has `asyncio` available. It is compatible with Python 3.10, 3.11, and 3.12. The framework itself has very few hard dependencies, so it installs quickly and stays lightweight:

- `anyio>=3.7` — cross-backend async support (`asyncio` and `trio`)
- `orjson>=3.10` — high-performance JSON serialization

## Install with pip

The simplest way to install Renus is from PyPI:

```bash
pip install renus
```

This installs the core framework, which is all you need to create and serve basic applications.

### Optional extras

Renus ships optional dependencies grouped into extras so you can install exactly what you need:

| Extra      | Provides                                        |
| ---------- | ----------------------------------------------- |
| `mongo`    | MongoDB support (`pymongo>=4.7`)                |
| `mysql`    | MySQL support (`aiomysql>=0.3`)                 |
| `redis`    | Redis support (`redis>=5.0`)                    |
| `server`   | ASGI server (`uvicorn>=0.29`)                   |
| `all`      | Everything above (`mongo`, `mysql`, `redis`, `server`) |
| `dev`      | Development and benchmarking tools              |

To install an optional extra:

```bash
pip install renus[server]
```

You can combine multiple extras with commas:

```bash
pip install renus[mongo,mysql,redis,server]
```

Or install everything at once:

```bash
pip install renus[all]
```

## Install from source

If you want to use the latest source code (for example, to contribute or to run against an unreleased version), clone the repository and install in editable mode:

```bash
git clone https://github.com/kak-smko/renus.git
cd renus
pip install -e .
```

For development, you can also install the development extras:

```bash
pip install -e .[dev]
```

## Installing an ASGI server

Renus is an ASGI framework, so you run your application with an ASGI server such as **uvicorn**:

```bash
pip install renus[server]
# or
pip install uvicorn
```

Once installed, you can serve your application (see the [Quick Start](/docs/starting/quick_start.md) guide for a full example):

```bash
uvicorn main:app --host 127.0.0.1 --port 4000 --reload
```

## Next steps

With Renus installed, move on to the [Quick Start](/docs/starting/quick_start.md) guide to build your first application, or review the [Project Structure](/docs/starting/project_structure.md) documentation to understand how a Renus project is organized.
