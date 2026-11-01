### Cross-Framework Benchmark Results

Real HTTP/1.1 keep-alive load test of `renus` vs other Python web frameworks. Each framework serves the same routes and is hammered single-process with the bundled stdlib load tester.

- Python: 3.12.15
- Concurrency: 64 keep-alive connections
- Duration: 60.0s per endpoint

> These are **relative** numbers for a single machine/run. Absolute throughput is machine-dependent; rerun and take the median before drawing conclusions.

#### `plain` (`/plain`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 37,354 | 1.93 | 2.00 | 2.92 | 6.04 |
| renus | 32,468 | 2.22 | 2.31 | 3.25 | 5.86 |
| blacksheep | 31,078 | 2.28 | 2.40 | 3.40 | 5.45 |
| robyn | 24,817 | 2.55 | 2.64 | 3.21 | 8.52 |
| sanic | 24,585 | 2.96 | 3.07 | 3.28 | 5.36 |
| litestar | 18,419 | 3.76 | 4.75 | 4.88 | 8.77 |
| fastapi | 13,841 | 4.99 | 6.05 | 6.20 | 10.41 |

#### `json` (`/json`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 34,293 | 2.12 | 2.20 | 2.68 | 5.01 |
| renus | 31,221 | 2.30 | 2.41 | 3.38 | 7.92 |
| blacksheep | 27,706 | 2.61 | 2.72 | 3.38 | 5.77 |
| robyn | 24,731 | 2.56 | 2.63 | 3.54 | 8.55 |
| sanic | 23,868 | 3.04 | 3.16 | 3.74 | 7.25 |
| litestar | 18,805 | 3.85 | 4.00 | 4.89 | 8.54 |
| fastapi | 13,379 | 5.31 | 5.65 | 6.58 | 10.83 |

#### `user` (`/user/alice`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 32,397 | 2.22 | 2.32 | 3.31 | 5.63 |
| renus | 29,988 | 2.41 | 2.51 | 3.39 | 5.79 |
| blacksheep | 27,743 | 2.61 | 2.71 | 3.58 | 4.65 |
| sanic | 23,445 | 3.09 | 3.21 | 4.27 | 7.12 |
| robyn | 16,217 | 3.80 | 3.89 | 7.38 | 10.17 |
| litestar | 15,398 | 4.31 | 5.38 | 5.56 | 9.26 |
| fastapi | 11,493 | 6.30 | 6.53 | 7.47 | 10.71 |
