# Scheduling

Renus includes a lightweight task scheduler for running periodic or time-based jobs inside an application. Jobs are defined with a fluent, chainable builder, deduplicated by a unique key, and executed either inline or on background threads.

The scheduler lives in the `renus.schedule` module and is built on four pieces:

- **`Schedule`** — the fluent builder you use to define and run jobs.
- **Spec** (`renus/schedule/state.py`) — the dataclass that records *when* a job runs.
- **Matcher** (`renus/schedule/matcher.py`) — decides whether a job is due and whether the current time matches its schedule.
- **Runner** (`renus/schedule/runner.py`) — runs a job, optionally on a thread and with retries.

## The `Schedule` builder

A `Schedule` instance holds a single pending job definition. You chain methods to describe when the job should run, then call `do(...)` to register it.

```python
from renus.schedule import Schedule

# Run every 5 minutes
Schedule().every(5).minutes().do("flush_metrics", flush_metrics)

# Run daily at 09:30
Schedule().every().days().at(hour=9, minute=30).do("daily_report", send_report)

# Run weekly on Monday at 08:00, but never on Sundays
Schedule().every().weeks() \
    .at(day="Monday", hour=8) \
    .forget(days=["Sunday"]) \
    .do("weekly_cleanup", run_cleanup)
```

Every call to `every(n)` starts a fresh job spec, so a `Schedule` is normally built inline per job.

### Time units

Choose one unit after `every(n)`:

| Method     | Meaning                |
| ---------- | ---------------------- |
| `weeks()`  | Run every `n` weeks.   |
| `days()`   | Run every `n` days.    |
| `hours()`  | Run every `n` hours.   |
| `minutes()`| Run every `n` minutes. |
| `seconds()`| Run every `n` seconds. |

### Targeting a run time with `at`

`at()` narrows when the job is allowed to run. The fields you can set depend on the unit:

| Unit       | Available `at` fields                 |
| ---------- | ------------------------------------- |
| `weeks`    | `day`, `hour`, `minute`, `second`     |
| `days`     | `hour`, `minute`, `second`            |
| `hours`    | `minute`, `second`                    |
| `minutes`  | `second`                              |
| `seconds` | *(none)*                              |

- `day` expects a weekday name such as `"Monday"`. It only affects `weeks` jobs; for finer units it is ignored.
- `hour`, `minute`, and `second` expect integers.

A job only runs when *all* set fields match the current time.

### Skipping times with `forget`

`forget()` skips the job on specific days, hours, minutes, or seconds, whichever spans your unit:

| Unit       | `forget` field that applies |
| ---------- | --------------------------- |
| `weeks`    | `days`                      |
| `days`     | `hours`                     |
| `hours`    | `minutes`                   |
| `minutes`  | `seconds`                   |
| `seconds` | *(none)*                    |

Each field takes a list of values to exclude (weekday names for `days`, integers otherwise).

### Retries with `max_try`

`max_try(n)` sets the maximum number of attempts before a job is considered failed. The default is `3`.

### Time offset with `timedelta`

`timedelta(n)` shifts the time reference used to decide whether a job is due, in minutes. The default is `0`, so jobs evaluate against the current UTC time. Advance it to align evaluations with a local time zone offset relative to UTC.

## Registering and running jobs

### `do(key, func, *args, **kwargs)`

`do` registers `func` (bound with `*args`/`**kwargs`) under `key` — but only if the job is **due** and the current time **matches** the spec.

```python
Schedule().every().minutes().do("sync", sync_now, force=True)
```

Because `do` only registers on a due+match check, a `Schedule` is typically built and given a `do` call inside a loop that runs `run()` repeatedly (see below).

### `run(parallel=True)`

`run` executes every job currently registered on the schedule. It runs each job via `job()`, removes it from the pending list, and records the run time so it will not run again until its interval has elapsed.

```python
sched = Schedule()
sched.every().minutes().do("ping", ping)
sched.run(parallel=False)  # run inline
```

By default jobs run `parallel=True`, each on its own worker thread.

### `job(key, func, parallel=True)`

`job` runs a single job immediately. It records the run time in the persistent last-run cache, removes the job from the pending list, and serializes concurrent runs of the **same key** with a per-key lock. Different keys run concurrently.

```python
sched.job("ping", ping)  # on a background thread
sched.job("ping", ping, parallel=False)  # inline, still locked by key
```

## Deduplication and persistence

The scheduler tracks the last run time of every key and persists it to the cache backend under the `schedule_last_run` key (TTL 24 hours). This means:

- A job that has never run is always due.
- A job is due again only once `interval` (of its unit) has passed since its last run.
- The first two checks inside `do` — due and time match — together decide registration.

```python
sched = Schedule().every().minutes()
sched.do("k", lambda: None)
sched.run(parallel=False)

# A fresh schedule with the same key won't re-run "k" until the interval elapses.
sched2 = Schedule().every().minutes()
sched2.do("k", lambda: None)  # not registered: still within the interval
```

Because forensics and deduplication use the `Cache` behind the scenes, the schedule shares the configured cache backend with the rest of the app. See [Caching](/docs/development/caching.md).

## Threading and retry behavior

- **Same key never overlaps.** A per-key lock guarantees two runs of the same key do not run concurrently; the second waits for the first to finish.
- **Different keys run in parallel** when `parallel=True`.
- **Retries.** Each job runs via `run_with_retry`, which calls the job and on an exception retries up to `max_try` times before giving up.
- **Failures are logged, not raised.** A job that exhausts its retries logs an error and is removed / finalized; it does not propagate an exception out of the schedule runner.


## Driving a schedule from the app

`Schedule` is not wired to an automatic run loop — you drive it. A common pattern is to register jobs and run them from a lifespan startup task that sleeps between iterations. See [Lifespan & Background Tasks](/docs/development/lifespan_tasks.md) for how to run startup work.

```python
from renus.schedule import Schedule

async def run_scheduler(app, on_startup):
    if not on_startup:
        return
    while True:
        sched = Schedule()
        sched.every().minutes().do("prune", prune_old_rows)
        sched.run()
        await asyncio.sleep(60)

app = App(on_startup=[run_scheduler])
```
