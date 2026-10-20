# Cross-Framework Benchmark — renus vs. the field

Real-HTTP, end-to-end comparison of **renus** against other popular Python web
frameworks:

| Framework  | Interface |
|------------|-----------|
| `renus`    | ASGI (uvicorn) |
| `pur_uvicorn` | native ASGI (uvicorn) |
| `fastapi`  | ASGI (uvicorn) |
| `litestar` | ASGI (uvicorn) |
| `blacksheep`| ASGI (uvicorn) |
| `sanic`    | own ASGI server |
| `robyn`    | own Rust-core server |

Every framework serves an **identical route set** from `servers/`:

```
GET /plain          -> text/plain        "Hello, World!"
GET /json           -> application/json  {"message": "Hello, World!"}
GET /user/<name>    -> application/json  {"name": <name>}
```

Each server is run **single-process / single-worker** so the number reflects the
framework dispatch + serialization path, not multi-worker scaling.

## Quick start

```bash
venv/bin/python benchmarks/compare.py --duration 10 --concurrency 64
```

Default: all frameworks, `--duration 5`, `--concurrency 64`. Options:

| Flag | Description |
|------|-------------|
| `--frameworks` | Subset to run, e.g. `renus fastapi sanic` |
| `--endpoints`  | Subset of `plain json user` |
| `-d` / `--duration` | Seconds per endpoint |
| `-c` / `--concurrency` | Keep-alive connections |
| `-o` / `--output` | Markdown file (default `RESULTS.md`) |

Results are printed to stdout and written to `RESULTS.md`.

## How it works

1. `compare.py` launches each framework's server (`servers/<name>.py`) as a
   subprocess on its own loopback port, using `DEVNULL` stdio (so frameworks
   that fork workers can never deadlock the orchestrator).
2. It warms each endpoint, then hammers it with the same keep-alive load via the
   bundled stdlib loader (`../loadtest.py`, `_run`).
3. Per-framework requests/second + latency percentiles are collected and ranked
   per endpoint.

The load tester and latency math are shared with `benchmarks/loadtest.py`, so
the comparison uses the exact same transport machinery as renus' own load test.

## Interpreting the numbers

- These are **relative** results for a single machine and single run. Absolute
  throughput is highly machine-dependent. Rerun a few times and take the median
  for anything serious (see the stability tips in `../README.md`).
- Python frameworks that lean on C/Rust extensions (BlackSheep, Robyn) tend to
  top the table; the gap narrows on workloads dominated by Python-side work.
- Sanic and Robyn bring their own servers, so their numbers include their own
  server implementation; the ASGI group (renus/pur_uvicorn/FastAPI/Litestar/BlackSheep)
  is the apples-to-apples group because they all share uvicorn. `pur_uvicorn` is
  a minimal native ASGI app and serves as the lower-overhead uvicorn baseline.

