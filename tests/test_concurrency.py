from __future__ import annotations

import asyncio
import os
import threading
import time

import pytest

from renus.util.concurrency import (
    iterate_in_threadpool,
    run_in_processpool,
    run_in_threadpool,
)

def _add(a, b):
    return a + b

def _double(n: int) -> int:
    return n * 2

def _slow() -> str:
    time.sleep(0.05)
    return "done"

def _current_pid() -> int:
    return os.getpid()

def _thread_name() -> str:
    return threading.current_thread().name

def _boom_process() -> None:
    raise RuntimeError("proc-boom")

class TestRunInThreadpool:
    @pytest.mark.asyncio
    async def test_returns_callable_result(self):
        assert await run_in_threadpool(_add, 2, 5) == 7

    @pytest.mark.asyncio
    async def test_forwards_keyword_arguments(self):
        assert await run_in_threadpool(_add, a=10, b=32) == 42

    @pytest.mark.asyncio
    async def test_runs_off_the_event_loop_thread(self):
        assert await run_in_threadpool(_thread_name) != threading.current_thread().name

    @pytest.mark.asyncio
    async def test_blocks_the_caller_until_result_ready(self):
        start = time.monotonic()
        result = await run_in_threadpool(_slow)
        elapsed = time.monotonic() - start
        assert result == "done"
        assert elapsed >= 0.04

    @pytest.mark.asyncio
    async def test_propagates_exceptions(self):
        def boom():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await run_in_threadpool(boom)

    @pytest.mark.asyncio
    async def test_concurrent_calls_share_the_pool(self):
        results = [run_in_threadpool(_double, i) for i in range(50)]
        assert await asyncio.gather(*results) == [i * 2 for i in range(50)]

class TestIterateInThreadpool:
    @pytest.mark.asyncio
    async def test_drains_sync_iterator(self):
        collected = [x async for x in iterate_in_threadpool(iter([1, 2, 3]))]
        assert collected == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_handles_empty_iterator(self):
        collected = [x async for x in iterate_in_threadpool(iter([]))]
        assert collected == []

    @pytest.mark.asyncio
    async def test_streams_async_generator(self):
        async def gen():
            yield 1
            yield 2
            yield 3

        collected = [x async for x in iterate_in_threadpool(gen())]
        assert collected == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_preserves_iterator_order(self):
        collected = [x async for x in iterate_in_threadpool(iter(range(10)))]
        assert collected == list(range(10))

class TestRunInProcesspool:
    @pytest.mark.asyncio
    async def test_returns_callable_result(self):
        assert await run_in_processpool(_double, 21) == 42

    @pytest.mark.asyncio
    async def test_forwards_keyword_arguments(self):
        assert await run_in_processpool(_add, a=19, b=23) == 42

    @pytest.mark.asyncio
    async def test_runs_in_a_different_process(self):
        assert await run_in_processpool(_current_pid) != os.getpid()

    @pytest.mark.asyncio
    async def test_propagates_exceptions(self):
        with pytest.raises(RuntimeError, match="proc-boom"):
            await run_in_processpool(_boom_process)

    @pytest.mark.asyncio
    async def test_concurrent_calls_share_the_pool(self):
        results = [run_in_processpool(_double, i) for i in range(20)]
        assert await asyncio.gather(*results) == [i * 2 for i in range(20)]
