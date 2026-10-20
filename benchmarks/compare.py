from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from benchmarks.loadtest import Stats, _percentile, _run

FRAMEWORKS = ["renus", "pur_uvicorn", "fastapi", "litestar", "blacksheep", "sanic", "robyn"]
ENDPOINTS = ["plain", "json", "user"]

_BASE_PORT = 8300

def _wait_port(host: str, port: int, proc: subprocess.Popen, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False

def _start_server(name: str, host: str, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, "-m", f"benchmarks.servers.{name}", "--host", host, "--port", str(port)],
        cwd=_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_port(host, port, proc):
        proc.kill()
        raise RuntimeError(f"{name}: server did not start (exit={proc.poll()})")
    return proc

def _endpoint_path(name: str, ep: str) -> str:
    return {
        "plain": "/plain",
        "json": "/json",
        "user": "/user/alice",
    }[ep]

def _measure(
    name: str,
    host: str,
    port: int,
    enum_eps: list[str],
    concurrency: int,
    duration: float,
) -> dict[str, Stats]:
    stats: dict[str, Stats] = {}

    for ep in enum_eps:
        path = _endpoint_path(name, ep)
        try:
            asyncio.run(_run(host, port, path, concurrency, 0.5, -1, 3.0))
        except (OSError, ValueError) as exc:
            print(f"[warn] {name}/{ep} warm-up failed: {exc}")
    for ep in enum_eps:
        path = _endpoint_path(name, ep)
        stats[ep] = asyncio.run(_run(host, port, path, concurrency, duration, -1, 3.0))
    return stats

def _report(
    results: dict[str, dict[str, Stats]],
    enum_eps: list[str],
    duration: float,
    concurrency: int,
) -> None:
    heading = "=" * 70
    print(heading)
    print("       Cross-framework HTTP benchmark (requests/second, higher is better)")
    print(heading)
    print(f"python      : {'.'.join(map(str, sys.version_info[:3]))}")
    print(f"concurrency : {concurrency} keep-alive connections")
    print(f"duration    : {duration}s per endpoint")
    print(heading)

    for ep in enum_eps:
        print(f"\n-- {ep} ({_endpoint_path('', ep)}) --")
        print(f"{'framework':<14}{'req/s':>10}{'p50':>10}{'p90':>10}{'p99':>10}{'max':>10}")
        print("-" * 70)
        ordered = sorted(results.items(), key=lambda kv: kv[1][ep].total / duration, reverse=True)
        for name, stats_map in ordered:
            st = stats_map[ep]
            rps = st.total / duration
            lat = sorted(st.latencies)
            to_ms = 1e3
            _pc = _percentile
            print(
                f"{name:<14}{rps:>10,.0f}"
                f"{_pc(lat, 50) * to_ms:>10.2f}{_pc(lat, 90) * to_ms:>10.2f}"
                f"{_pc(lat, 99) * to_ms:>10.2f}"
                f"{max(lat) * to_ms if lat else float('nan'):>10.2f}"
            )
    print(heading)

def _write_markdown(
    results: dict[str, dict[str, Stats]],
    enum_eps: list[str],
    duration: float,
    concurrency: int,
) -> str:
    lines: list[str] = []
    lines.append("# Cross-Framework Benchmark Results")
    lines.append("")
    lines.append(
        "Real HTTP/1.1 keep-alive load test of `renus` vs other Python web "
        "frameworks. Each framework serves the same routes and is hammered "
        "single-process with the bundled stdlib load tester."
    )
    lines.append("")
    lines.append(f"- Python: {'.'.join(map(str, sys.version_info[:3]))}")
    lines.append(f"- Concurrency: {concurrency} keep-alive connections")
    lines.append(f"- Duration: {duration}s per endpoint")
    lines.append("")
    lines.append("> These are **relative** numbers for a single machine/run. "
                 "Absolute throughput is machine-dependent; rerun and take the "
                 "median before drawing conclusions.")
    lines.append("")
    for ep in enum_eps:
        lines.append(f"## `{ep}` (`{_endpoint_path('', ep)}`)")
        lines.append("")
        lines.append("| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |")
        lines.append("|-----------|------:|---------:|---------:|---------:|---------:|")
        ordered = sorted(
            results.items(), key=lambda kv: kv[1][ep].total / duration, reverse=True
        )
        for name, stats_map in ordered:
            st = stats_map[ep]
            rps = st.total / duration
            lat = sorted(st.latencies)
            _pc = _percentile
            lines.append(
                f"| {name} | {rps:,.0f} | {_pc(lat, 50) * 1e3:.2f} | {_pc(lat, 90) * 1e3:.2f} | "
                f"{_pc(lat, 99) * 1e3:.2f} | {max(lat) * 1e3 if lat else float('nan'):.2f} |"
            )
        lines.append("")
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RESULTS.md")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return out_path

def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-framework HTTP benchmark")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("-c", "--concurrency", type=int, default=64)
    parser.add_argument("-d", "--duration", type=float, default=10.0)
    parser.add_argument(
        "--frameworks",
        nargs="*",
        default=FRAMEWORKS,
        help="subset of frameworks to run (default: all)",
    )
    parser.add_argument(
        "--endpoints", nargs="*", default=ENDPOINTS, choices=ENDPOINTS,
    )
    parser.add_argument("-o", "--output", default="RESULTS.md")
    args = parser.parse_args()

    frameworks = [f for f in args.frameworks if f in FRAMEWORKS]
    if not frameworks:
        print("no valid frameworks selected", file=sys.stderr)
        sys.exit(1)

    results: dict[str, dict[str, Stats]] = {}
    for idx, name in enumerate(frameworks):
        port = _BASE_PORT + idx
        print(f"[bench] {name}: starting on :{port}", flush=True)
        proc = _start_server(name, args.host, port)
        try:
            results[name] = _measure(name, args.host, port, args.endpoints, args.concurrency, args.duration)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
        print(f"[bench] {name}: done", flush=True)

    _report(results, args.endpoints, args.duration, args.concurrency)
    out = _write_markdown(results, args.endpoints, args.duration, args.concurrency)
    print(f"\nResults written to {out}")

if __name__ == "__main__":
    main()
