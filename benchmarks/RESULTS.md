### Cross-Framework Benchmark Results

Real HTTP/1.1 keep-alive load test of `renus` vs other Python web frameworks. Each framework serves the same routes and is hammered single-process with the bundled stdlib load tester.

- Python: 3.12.15
- Concurrency: 64 keep-alive connections
- Duration: 60.0s per endpoint

> These are **relative** numbers for a single machine/run. Absolute throughput is machine-dependent; rerun and take the median before drawing conclusions.

#### `plain` (`/plain`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 33,764 | 2.01 | 2.14 | 2.96 | 5.91 |
| renus | 28,845 | 2.36 | 2.47 | 3.23 | 5.63 |
| blacksheep | 27,124 | 2.48 | 2.59 | 4.49 | 8.71 |
| sanic | 18,773 | 3.63 | 3.76 | 5.54 | 7.10 |
| robyn | 17,317 | 3.67 | 3.76 | 4.28 | 7.47 |
| litestar | 13,670 | 4.96 | 5.16 | 6.97 | 8.68 |
| fastapi | 10,367 | 6.59 | 6.80 | 7.26 | 11.61 |

#### `json` (`/json`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 30,058 | 2.28 | 2.37 | 3.06 | 5.74 |
| renus | 27,296 | 2.49 | 2.62 | 4.35 | 8.90 |
| blacksheep | 22,239 | 3.02 | 3.14 | 5.05 | 6.84 |
| robyn | 17,216 | 3.69 | 3.78 | 4.34 | 9.29 |
| sanic | 16,378 | 3.92 | 5.74 | 5.87 | 7.38 |
| litestar | 13,202 | 5.18 | 5.38 | 5.85 | 10.67 |
| fastapi | 9,421 | 7.21 | 7.48 | 9.35 | 12.31 |

#### `user` (`/user/alice`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 28,562 | 2.39 | 2.49 | 3.46 | 6.26 |
| renus | 26,138 | 2.60 | 2.73 | 4.41 | 6.50 |
| blacksheep | 22,516 | 2.98 | 3.09 | 5.02 | 7.59 |
| sanic | 15,766 | 3.93 | 5.82 | 5.95 | 7.92 |
| robyn | 11,854 | 5.31 | 5.44 | 8.42 | 11.92 |
| litestar | 11,487 | 5.94 | 6.16 | 7.46 | 12.23 |
| fastapi | 8,016 | 8.51 | 8.78 | 9.34 | 16.11 |
