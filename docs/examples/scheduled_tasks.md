# Scheduled Tasks

Define a job with the fluent `Schedule` builder. This example registers a job due every minute and runs the pending work inline:

```python
from renus.schedule import Schedule


def flush_metrics():
    print("metrics flushed")


schedule = Schedule()
schedule.every().minutes().do("flush_metrics", flush_metrics)
schedule.run(parallel=False)
```

`do()` registers a job only when its interval is due and its time constraints match. In a service, call the scheduler regularly from a managed loop so it can check for due work; do not block an async request handler with a long-running loop.

See [Scheduling](../development/scheduling.md) for time units, retries, and parallel execution.
