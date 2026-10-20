from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

@dataclass
class Stats:

    total: int = 0
    errors: int = 0
    bytes_received: int = 0
    latencies: list = field(default_factory=list)

async def _send_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    path: str,
    host: str,
) -> int:
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: renus-benchmark\r\n"
        "Accept: */*\r\n"
        "Connection: keep-alive\r\n"
        "\r\n"
    ).encode("latin-1")
    writer.write(request)
    await writer.drain()

    header_bytes = await reader.readuntil(b"\r\n\r\n")
    status_line = header_bytes.split(b"\r\n", 1)[0]
    if not status_line.startswith(b"HTTP/1."):
        raise ValueError(f"bad status line: {status_line!r}")

    content_length: int | None = None
    for line in header_bytes.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            content_length = int(line.split(b":", 1)[1].strip())
    body = bytearray()
    if content_length is not None:
        while len(body) < content_length:
            chunk = await reader.readexactly(content_length - len(body))
            body += chunk
    else:

        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            body += chunk
    return len(body)

async def _worker(
    host: str,
    port: int,
    path: str,
    stop: asyncio.Event,
    results: asyncio.Queue,
    stats: Stats,
    connect_timeout: float,
) -> None:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=connect_timeout
        )
    except (OSError, asyncio.TimeoutError) as exc:
        results.put_nowait(("error", None, str(exc)))
        return

    try:
        while not stop.is_set():
            started = time.perf_counter()
            try:
                nbytes = await _send_request(reader, writer, path, host)
                elapsed = time.perf_counter() - started
                stats.total += 1
                stats.bytes_received += nbytes
                stats.latencies.append(elapsed)
            except (OSError, asyncio.IncompleteReadError, ValueError) as exc:
                stats.errors += 1
                results.put_nowait(("error", None, str(exc)))

                reconnect_ok = False
                for _ in range(3):
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, port),
                            timeout=connect_timeout,
                        )
                        reconnect_ok = True
                        break
                    except (OSError, asyncio.TimeoutError):
                        await asyncio.sleep(0.1)
                if not reconnect_ok:
                    return
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.TimeoutError):
            pass

async def _run(
    host: str,
    port: int,
    path: str,
    concurrency: int,
    duration: float,
    max_requests: int,
    connect_timeout: float,
) -> Stats:
    stop = asyncio.Event()
    results: asyncio.Queue = asyncio.Queue()
    stats = Stats()

    workers = [
        asyncio.create_task(
            _worker(host, port, path, stop, results, stats, connect_timeout)
        )
        for _ in range(concurrency)
    ]

    deadline = time.perf_counter() + duration
    while time.perf_counter() < deadline:
        if max_requests >= 0 and stats.errors + len(stats.latencies) >= max_requests:
            break
        await asyncio.sleep(0.5)

    stop.set()
    await asyncio.gather(*workers, return_exceptions=True)
    return stats

def _percentile(sorted_latencies: list, p: float) -> float:
    if not sorted_latencies:
        return 0.0
    index = int(len(sorted_latencies) * p / 100)
    return sorted_latencies[max(0, min(index, len(sorted_latencies) - 1))]

def _report(stats: Stats, duration: float) -> None:
    total = stats.total
    errors = stats.errors
    elapsed = duration
    rps = total / elapsed if elapsed > 0 else 0.0
    lat = sorted(stats.latencies)

    heading = "=" * 60
    print(heading)
    print("       renus end-to-end HTTP load test")
    print(heading)
    print(f"requests      : {total}   ({total + errors} attempts, {errors} errors)")
    print(f"bytes received: {stats.bytes_received}  ({stats.bytes_received / 1024 / 1024:.1f} MB)")
    print(f"elapsed       : {elapsed:.2f}s")
    print(f"throughput    : {rps:,.0f} req/s")
    print(heading)
    print(f"{'latency':<14}{'p50':>10}{'p90':>10}{'p99':>10}{'max':>10}")
    print("-" * 60)
    to_ms = 1000.0
    if lat:
        print(
            f"{'':<14}"
            f"{_percentile(lat, 50) * to_ms:>10.2f}ms"
            f"{_percentile(lat, 90) * to_ms:>10.2f}ms"
            f"{_percentile(lat, 99) * to_ms:>10.2f}ms"
            f"{max(lat) * to_ms:>10.2f}ms"
        )
    else:
        print(f"{'':<14}{'n/a':>10}")
    if errors:
        print(heading)
        print(f"!! {errors} requests failed — check the server logs / connectivity.")
    print(heading)

async def _amain(args: argparse.Namespace) -> None:
    split = urlsplit(args.url)
    if split.scheme != "http":
        raise ValueError("only http:// URLs are supported")
    host = split.hostname or "127.0.0.1"
    port = split.port or 80
    path = split.path or "/"
    if split.query:
        path += "?" + split.query

    duration = float(args.duration)
    started = time.perf_counter()
    stats = await _run(
        host,
        port,
        path,
        args.concurrency,
        duration,
        args.requests,
        args.connect_timeout,
    )
    elapsed = time.perf_counter() - started
    _report(stats, elapsed)

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="End-to-end HTTP load test for the renus framework",
        epilog=(
            "Examples:\n"
            "  %(prog)s --url http://127.0.0.1:8000/json --concurrency 100\n"
            "  %(prog)s --serve --duration 15 --concurrency 64\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/plain", help="target URL")
    parser.add_argument("-c", "--concurrency", type=int, default=100, help="keep-alive connections")
    parser.add_argument("-d", "--duration", type=float, default=10, help="seconds to run")
    parser.add_argument("-n", "--requests", type=int, default=-1, help="stop after N requests (-1 = by time)")
    parser.add_argument("--connect-timeout", type=float, default=3.0, help="connection timeout (s)")
    parser.add_argument("--port", type=int, default=8000, help="port for --serve")
    
    return parser

def main() -> None:
    args = _build_parser().parse_args()

    server_proc: subprocess.Popen | None = None
    try:
        if args.serve:
            split = urlsplit(args.url)
            port = split.port or args.port
            args.url = f"http://{split.hostname or '127.0.0.1'}:{port}{split.path or '/'}"
            env = dict(os.environ)
            server_proc = subprocess.Popen(
                [sys.executable, os.path.join(_ROOT, "benchmarks", "server.py"),
                 "--port", str(port)],
                cwd=_ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with __import__("socket").create_connection(
                        ("127.0.0.1", port), timeout=1
                    ):
                        break
                except OSError:
                    if server_proc.poll() is not None:
                        raise RuntimeError("server exited during startup")
                    time.sleep(0.25)
            else:
                raise RuntimeError("server did not start within 15s")
            time.sleep(0.5)

        asyncio.run(_amain(args))
    finally:
        if server_proc is not None:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_proc.kill()

if __name__ == "__main__":
    main()
