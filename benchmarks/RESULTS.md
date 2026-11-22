### Cross-Framework Benchmark Results

Real HTTP/1.1 keep-alive load test of `renus` vs other Python web frameworks. Each framework serves the same routes and is hammered single-process with the bundled stdlib load tester.

- Python: 3.12.16
- Concurrency: 64 keep-alive connections
- Duration: 60.0s per endpoint

> These are **relative** numbers for a single machine/run. Absolute throughput is machine-dependent; rerun and take the median before drawing conclusions.

#### `plain` (`/plain`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 37,204 | 1.73 | 1.98 | 2.40 | 6.38 |
| renus | 36,624 | 1.75 | 1.94 | 2.31 | 5.38 |
| blacksheep | 35,555 | 1.78 | 2.01 | 2.52 | 11.85 |
| robyn | 32,336 | 1.96 | 2.12 | 2.64 | 12.80 |
| sanic | 27,210 | 2.34 | 2.67 | 3.15 | 13.74 |
| litestar | 21,781 | 2.90 | 3.34 | 3.83 | 10.42 |
| fastapi | 15,911 | 4.02 | 4.54 | 5.36 | 11.99 |

#### `json` (`/json`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 36,345 | 1.72 | 2.04 | 2.46 | 7.14 |
| renus | 34,566 | 1.82 | 2.08 | 2.49 | 5.70 |
| blacksheep | 32,221 | 2.00 | 2.23 | 2.68 | 13.62 |
| robyn | 32,195 | 1.97 | 2.14 | 2.63 | 16.44 |
| sanic | 26,773 | 2.40 | 2.68 | 3.20 | 13.61 |
| litestar | 21,484 | 2.99 | 3.38 | 3.87 | 12.57 |
| fastapi | 14,951 | 4.25 | 4.82 | 5.71 | 12.68 |

#### `user` (`/user/alice`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 35,420 | 1.77 | 2.02 | 2.56 | 7.99 |
| renus | 34,134 | 1.89 | 2.13 | 2.50 | 6.59 |
| blacksheep | 32,132 | 1.99 | 2.26 | 2.81 | 12.06 |
| robyn | 26,982 | 2.29 | 2.60 | 2.93 | 16.30 |
| sanic | 26,229 | 2.43 | 2.74 | 3.37 | 14.35 |
| litestar | 19,144 | 3.36 | 3.66 | 4.27 | 12.51 |
| fastapi | 12,877 | 4.92 | 5.59 | 6.47 | 12.85 |
