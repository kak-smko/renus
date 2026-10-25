# Scheduled Tasks

Define a job with the fluent `Schedule` builder. This example registers a job due every minute and runs the pending work inline:

```python
import asyncio

from renus.schedule import Schedule


def flush_metrics():
    print("metrics flushed")


async def main():
    schedule = Schedule()
    schedule.every().minutes().do("flush_metrics", flush_metrics)
    await schedule.run(parallel=False)


asyncio.run(main())
```

Jobs may also be `async def` functions; `await schedule.run()` awaits their completion. `do()` registers a job only when its interval is due and its time constraints match. In a service, call the scheduler regularly from a managed loop so it can check for due work; do not block an async request handler with a long-running loop.

See [Scheduling](../development/scheduling.md) for time units, retries, and parallel execution.
