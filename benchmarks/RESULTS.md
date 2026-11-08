### Cross-Framework Benchmark Results

Real HTTP/1.1 keep-alive load test of `renus` vs other Python web frameworks. Each framework serves the same routes and is hammered single-process with the bundled stdlib load tester.

- Python: 3.12.16
- Concurrency: 64 keep-alive connections
- Duration: 60.0s per endpoint

> These are **relative** numbers for a single machine/run. Absolute throughput is machine-dependent; rerun and take the median before drawing conclusions.

#### `plain` (`/plain`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 33,978 | 2.00 | 2.08 | 2.86 | 7.55 |
| renus | 28,635 | 2.39 | 2.48 | 3.09 | 6.81 |
| blacksheep | 26,576 | 2.52 | 2.63 | 4.58 | 13.38 |
| sanic | 18,357 | 3.69 | 3.80 | 5.51 | 17.56 |
| robyn | 17,539 | 3.60 | 3.69 | 5.66 | 20.49 |
| litestar | 13,718 | 4.95 | 5.09 | 7.02 | 15.07 |
| fastapi | 10,160 | 6.69 | 6.88 | 8.82 | 16.12 |

#### `json` (`/json`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 29,848 | 2.27 | 2.36 | 3.55 | 9.63 |
| renus | 26,862 | 2.49 | 2.60 | 4.48 | 8.22 |
| blacksheep | 21,713 | 3.01 | 3.16 | 5.11 | 15.47 |
| robyn | 17,506 | 3.60 | 3.68 | 5.81 | 21.41 |
| sanic | 15,647 | 3.93 | 5.74 | 5.84 | 20.05 |
| litestar | 13,166 | 5.16 | 5.34 | 6.95 | 17.64 |
| fastapi | 9,244 | 7.29 | 7.52 | 10.39 | 18.43 |

#### `user` (`/user/alice`)

| Framework | req/s | p50 (ms) | p90 (ms) | p99 (ms) | max (ms) |
|-----------|------:|---------:|---------:|---------:|---------:|
| pur_uvicorn | 28,384 | 2.40 | 2.49 | 3.50 | 10.84 |
| renus | 25,852 | 2.63 | 2.73 | 4.15 | 7.49 |
| blacksheep | 21,514 | 3.02 | 3.20 | 5.13 | 16.31 |
| sanic | 15,311 | 3.98 | 5.77 | 5.87 | 18.97 |
| robyn | 11,883 | 5.21 | 5.35 | 8.43 | 23.27 |
| litestar | 11,554 | 5.88 | 6.04 | 7.99 | 17.56 |
| fastapi | 7,990 | 8.51 | 8.76 | 9.86 | 18.50 |
