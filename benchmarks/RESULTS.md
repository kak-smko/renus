### Cross-Framework Benchmark Results

Real HTTP/1.1 keep-alive load test of `renus` vs other Python web frameworks. Each framework serves the same routes and is hammered single-process with the bundled stdlib load tester.

- Python: 3.12.16
- Concurrency: 64 keep-alive connections
- Duration: 60.0s per endpoint

> These are **relative** numbers for a single machine/run. Absolute throughput is machine-dependent; rerun and take the median before drawing conclusions.

#### `plain` (`/plain`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 31,038 | 2.04 | 2.34 | 2.75 | 7.53 |
| renus | 30,431 | 2.06 | 2.39 | 3.00 | 6.06 |
| blacksheep | 29,414 | 2.16 | 2.41 | 2.97 | 11.64 |
| robyn | 27,119 | 2.35 | 2.52 | 3.04 | 14.13 |
| sanic | 21,384 | 3.03 | 3.15 | 4.35 | 13.86 |
| litestar | 15,583 | 4.09 | 4.31 | 5.92 | 12.94 |
| fastapi | 12,001 | 5.39 | 5.58 | 7.17 | 13.65 |

#### `json` (`/json`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 31,058 | 2.02 | 2.40 | 2.79 | 8.56 |
| renus | 29,608 | 2.17 | 2.39 | 2.88 | 7.01 |
| robyn | 27,105 | 2.38 | 2.52 | 2.98 | 19.99 |
| blacksheep | 25,438 | 2.55 | 2.67 | 3.52 | 12.14 |
| sanic | 20,079 | 3.22 | 3.34 | 4.91 | 13.72 |
| litestar | 15,059 | 4.16 | 4.81 | 6.13 | 14.44 |
| fastapi | 11,042 | 5.85 | 6.04 | 7.57 | 16.20 |

#### `user` (`/user/alice`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 30,848 | 2.05 | 2.25 | 2.84 | 9.02 |
| renus | 28,052 | 2.29 | 2.51 | 3.73 | 7.64 |
| blacksheep | 25,524 | 2.53 | 2.66 | 3.65 | 13.16 |
| sanic | 19,771 | 3.25 | 3.39 | 5.02 | 17.15 |
| robyn | 19,326 | 3.17 | 3.55 | 4.00 | 17.10 |
| litestar | 13,020 | 4.72 | 6.32 | 6.78 | 14.00 |
| fastapi | 9,621 | 6.70 | 6.94 | 8.49 | 16.32 |
