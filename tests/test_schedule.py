import datetime
import threading
import time
from unittest.mock import patch

import pytest

from renus.schedule import (
    Schedule,
    run_threaded,
    thread_exception_handler,
)
from renus.schedule.matcher import is_due, matches
from renus.schedule.runner import run_with_retry
from renus.schedule.state import Spec, interval_delta

class _FakeCache:

    schedule_log: object
    runner_log: object

    def __init__(self):
        self.store = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def put(self, key, value, expire=60):
        self.store[key] = value

@pytest.fixture(autouse=True)
def cache():
    fake = _FakeCache()
    with (
        patch("renus.schedule.schedule.Cache", lambda: fake),
        patch("renus.schedule.schedule.Log") as schedule_log,
        patch("renus.schedule.runner.Log") as runner_log,
    ):
        fake.schedule_log = schedule_log
        fake.runner_log = runner_log
        yield fake

def _now(year=2026, month=9, day=3, hour=10, minute=0, second=0):
    return datetime.datetime(
        year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
    )

class TestBuilder:

    def test_chaining_returns_self(self):
        s = Schedule()
        assert s.every(2) is s
        assert s.weeks() is s
        assert s.days() is s
        assert s.hours() is s
        assert s.minutes() is s
        assert s.secounds() is s
        assert s.at(day="Monday") is s
        assert s.forget(hours=[3]) is s
        assert s.max_try(5) is s
        assert s.timedelta(10) is s

    def test_every_resets_pending_spec(self):
        s = Schedule().weeks().at(hour=9).max_try(5)
        s.every(3)
        assert s._spec.unit is None
        assert s._spec.interval == 3
        assert s._spec.max_try == 3
        assert s._spec.at.hour is None

    def test_setters_populate_spec(self):
        s = Schedule()
        s.weeks().at(day="Mon", hour=9).forget(days=["Sun"]).max_try(7).timedelta(100)
        assert s._spec.unit == "weeks"
        assert s._spec.at.day == "Mon"
        assert s._spec.at.hour == 9
        assert s._spec.forget.day == ["Sun"]
        assert s._spec.max_try == 7
        assert s._spec.timedelta == 100

class TestMatcher:

    def test_is_due_when_never_run(self):
        spec = Spec(unit="minutes")
        assert is_due("k", {}, _now(), spec) is True

    def test_is_due_when_interval_elapsed(self):
        spec = Spec(unit="minutes")
        now = _now()
        last = {"k": now - datetime.timedelta(minutes=5)}
        assert is_due("k", last, now, spec) is True

    def test_not_due_within_interval(self):
        spec = Spec(unit="minutes")
        now = _now()
        last = {"k": now - datetime.timedelta(seconds=10)}
        assert is_due("k", last, now, spec) is False

    def test_unknown_unit_never_due(self):
        now = _now()
        assert is_due("k", {}, now, Spec(unit="bogus")) is False
        assert matches(Spec(unit="bogus"), now) is False

    def test_at_hour_filters(self):
        spec = Spec(unit="hours")
        spec.at.minute = 15
        assert matches(spec, _now(minute=15)) is True
        assert matches(spec, _now(minute=16)) is False

    def test_at_weekday_only_matters_for_weeks(self):

        spec = Spec(unit="days")
        spec.at.day = "Monday"
        assert matches(spec, _now(day=3)) is True

    def test_at_weekday_for_weeks(self):
        spec = Spec(unit="weeks")
        spec.at.day = "Thursday"
        assert matches(spec, _now(day=3)) is True
        assert matches(spec, _now(day=7)) is False

    def test_forget_day_blocks(self):
        spec = Spec(unit="days")
        spec.forget.day = ["Thursday"]
        assert matches(spec, _now(day=3)) is False
        assert matches(spec, _now(day=7)) is True

    def test_forget_hour(self):
        spec = Spec(unit="hours")
        spec.forget.hour = [23]
        assert matches(spec, _now(hour=23)) is False
        assert matches(spec, _now(hour=10)) is True

    def test_forget_minute(self):
        spec = Spec(unit="minutes")
        spec.forget.minute = [30]
        assert matches(spec, _now(minute=30)) is False
        assert matches(spec, _now(minute=0)) is True

    def test_forget_second(self):
        spec = Spec(unit="secounds")
        spec.forget.second = [5]
        assert matches(spec, _now(second=5)) is False
        assert matches(spec, _now(second=6)) is True

    def test_interval_delta_per_unit(self):
        assert interval_delta("secounds", 5) == datetime.timedelta(seconds=5)
        assert interval_delta("minutes", 2) == datetime.timedelta(minutes=2)
        assert interval_delta("hours", 3) == datetime.timedelta(hours=3)
        assert interval_delta("days", 1) == datetime.timedelta(days=1)
        assert interval_delta("weeks", 2) == datetime.timedelta(weeks=2)

class TestRunner:

    def test_run_threaded_executes(self):
        event = threading.Event()

        def work():
            event.set()

        run_threaded(work)
        assert event.wait(timeout=2)

    def test_retry_succeeds_after_failures(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("not yet")

        run_with_retry(flaky, max_try=3, parallel=False)
        assert calls["n"] == 3

    def test_retry_exhausts_then_raises(self):
        calls = {"n": 0}

        def boom():
            calls["n"] += 1
            raise ValueError("always")

        with pytest.raises(ValueError):
            run_with_retry(boom, max_try=3, parallel=False)
        assert calls["n"] == 3

    def test_retry_multi_starts_thread(self):
        event = threading.Event()

        def work():
            event.set()

        run_with_retry(work, max_try=1, parallel=True)
        assert event.wait(timeout=2)

    def test_thread_exception_handler_logs(self, cache):
        exc = (RuntimeError, RuntimeError("boom"), None)
        thread_exception_handler(exc)
        cache.runner_log().error.assert_called_once()

class TestSchedule:

    def test_do_registers_when_due(self):
        sched = Schedule().every().minutes()
        sched.do("k", lambda: None)
        assert "k" in sched._job_list

    def test_do_skips_when_recently_run(self):
        sched = Schedule().every().minutes()

        sched._last_run["k"] = datetime.datetime.now(
            datetime.timezone.utc
        ) + datetime.timedelta(minutes=210)
        sched.do("k", lambda: None)
        assert "k" not in sched._job_list

    def test_do_respects_at_constraint(self):

        sched = Schedule().every().hours().at(minute=99)
        sched.do("k", lambda: None)
        assert "k" not in sched._job_list

    def test_do_binds_arguments(self):
        seen = []

        def record(*args, **kwargs):
            seen.append((args, kwargs))

        sched = Schedule().every().minutes()
        sched.do("k", record, 1, 2, c=3)
        sched._job_list["k"]()
        assert seen == [((1, 2), {"c": 3})]

    def test_job_runs_and_pops(self):
        calls = []
        sched = Schedule().every().minutes()
        sched.do("k", lambda: calls.append(1))
        sched.job("k", lambda: calls.append(1), parallel=False)
        assert calls == [1]
        assert "k" not in sched._job_list

    def test_job_persists_last_run(self, cache):
        sched = Schedule().every().minutes()
        sched.do("k", lambda: None)
        sched.job("k", lambda: None, parallel=False)
        assert cache.store["schedule_last_run"]["k"]
        assert "k" not in sched._job_list

    def test_last_run_prevents_reregister(self):
        sched = Schedule().every().minutes()
        sched.do("k", lambda: None)
        sched.job("k", lambda: None, parallel=False)

        sched2 = Schedule().every().minutes()
        sched2.do("k", lambda: None)
        assert "k" not in sched2._job_list

    def test_run_executes_all_and_clears(self):
        calls = []
        sched = Schedule().every().minutes()
        sched.do("a", lambda: calls.append("a"))
        sched.do("b", lambda: calls.append("b"))
        sched.run(parallel=False)
        assert sorted(calls) == ["a", "b"]
        assert sched._job_list == {}

    def test_run_multi_executes_on_threads(self):
        event = threading.Event()
        sched = Schedule().every().minutes()
        sched.do("k", lambda: event.set())
        sched.run(parallel=True)
        assert event.wait(timeout=2)
        assert sched._job_list == {}

    def test_same_key_runs_never_overlap(self):
        sched = Schedule().every().minutes()
        active = {"now": 0, "max": 0, "done": 0}
        entered = threading.Event()
        release = threading.Event()

        def slow():
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            entered.set()
            release.wait(timeout=5)
            active["now"] -= 1
            active["done"] += 1

        sched._job_list["k"] = slow
        sched.run(parallel=True)  
        assert entered.wait(timeout=2)

        sched._job_list["k"] = slow
        sched.run(parallel=True)
        assert active["now"] == 1
        assert active["max"] == 1

        release.set()  
        deadline = time.monotonic() + 5
        while active["done"] < 2 and time.monotonic() < deadline:
            time.sleep(0.01)

        assert active["done"] == 2  
        assert active["max"] == 1  

    def test_different_keys_run_in_parallel(self):
        sched = Schedule().every().minutes()
        entered = {"a": False, "b": False}
        release = threading.Event()

        def slow(name):
            entered[name] = True
            release.wait(timeout=5)

        sched._job_list["a"] = lambda: slow("a")
        sched._job_list["b"] = lambda: slow("b")
        sched.run(parallel=True)

        deadline = time.monotonic() + 5
        while (not entered["a"] or not entered["b"]) and time.monotonic() < deadline:
            time.sleep(0.01)

        assert entered["a"]
        assert entered["b"]
        release.set()

    def test_job_failure_logs_and_pops(self, cache):
        def boom():
            raise RuntimeError("x")

        sched = Schedule().secounds()
        sched._job_list["k"] = boom
        sched.job("k", boom, parallel=False)
        assert "k" not in sched._job_list
        cache.schedule_log().error.assert_called_once()
