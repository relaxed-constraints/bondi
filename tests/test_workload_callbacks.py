"""Callback delivery contracts across both backends and synchronous facades."""

import asyncio
import threading

import pytest
from pymongo.errors import OperationFailure

from bondi.couchbase import AsyncCouchbaseExecutor, CouchbaseExecutor, CouchbaseQuery
from bondi.execution import ExecutionResult
from bondi.mongodb import AsyncMongoExecutor, MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

METHODS = ["run", "explain", "profile"]


@pytest.fixture(params=["mongodb", "couchbase"])
def backend(request):
    if request.param == "mongodb":
        return (
            AsyncMongoExecutor,
            MongoExecutor,
            lambda i: MongoFindQuery(MongoCollectionRef("demo", "items"), {"i": i}),
            lambda: OperationFailure("database failure"),
        )
    pytest.importorskip("couchbase")
    from couchbase.exceptions import ParsingFailedException

    return (
        AsyncCouchbaseExecutor,
        CouchbaseExecutor,
        lambda i: CouchbaseQuery(f"SELECT {i}"),
        lambda: ParsingFailedException("database failure"),
    )


def work(backend, count):
    return Workload([WorkloadEntry(backend[2](i), pattern_id=i) for i in range(count)])


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 5))


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("awaitable", [False, True])
def test_sequential_progress_identity_and_timing(backend, method, awaitable):
    async def scenario():
        executor = backend[0](None)
        workload = work(backend, 3)
        seen = []
        loop = asyncio.get_running_loop()
        results = [ExecutionResult(7) for _ in workload]

        async def operation(query, **kwargs):
            index = next(i for i, e in enumerate(workload) if e.query is query)
            assert len(seen) == index  # Delivery occurs before the next query starts.
            return results[index]

        def record(index, entry, result):
            assert asyncio.get_running_loop() is loop
            assert entry is workload[index] and result is results[index]
            seen.append(index)

        async def callback(*args):
            await asyncio.sleep(0)
            record(*args)

        setattr(executor, method, operation)
        returned = await getattr(executor, method + "_workload")(
            workload, on_result=callback if awaitable else record
        )
        assert seen == [0, 1, 2]
        assert all(a is b for a, b in zip(returned, results, strict=True))
        assert all(r.elapsed_ms == 7 for r in returned)

    run(scenario())


@pytest.mark.parametrize("method", METHODS)
def test_concurrent_serialization_order_and_backpressure(backend, method):
    async def scenario():
        executor = backend[0](None, concurrency=2)
        workload = work(backend, 3)
        first_callback = asyncio.Event()
        first_query_done = asyncio.Event()
        seen, started = [], []
        active = 0

        async def operation(query, **kwargs):
            index = next(i for i, e in enumerate(workload) if e.query is query)
            started.append(index)
            if index == 0:
                await first_callback.wait()
                first_query_done.set()
            return ExecutionResult(index)

        async def callback(index, entry, result):
            nonlocal active
            assert active == 0
            active += 1
            seen.append(index)
            if index == 1:
                first_callback.set()
                await first_query_done.wait()
                await asyncio.sleep(0)
                assert started == [0, 1]  # Both workers await callback completion.
            await asyncio.sleep(0)
            active -= 1

        setattr(executor, method, operation)
        results = await getattr(executor, method + "_workload")(workload, on_result=callback)
        assert seen == [1, 0, 2]
        assert [r.elapsed_ms for r in results] == [0, 1, 2]

    run(scenario())


@pytest.mark.parametrize("keep_going", [False, True])
@pytest.mark.parametrize("timeout", [False, True])
def test_error_callbacks_and_fail_fast_draining(backend, keep_going, timeout):
    async def scenario():
        executor = backend[0](None, concurrency=2, continue_on_error=keep_going)
        workload = work(backend, 4)
        second_started, failed_delivered = asyncio.Event(), asyncio.Event()
        seen = []
        error = TimeoutError("deadline") if timeout else backend[3]()

        async def operation(query, **kwargs):
            index = next(i for i, e in enumerate(workload) if e.query is query)
            if index == 0:
                await second_started.wait()
                raise error
            if index == 1:
                second_started.set()
                await failed_delivered.wait()
            return ExecutionResult(index)

        def callback(index, entry, result):
            seen.append(index)
            if index == 0:
                assert result.error is error
                assert result.status == ("timeout" if timeout else "error")
                failed_delivered.set()

        executor.run = operation
        results = await executor.run_workload(workload, on_result=callback)
        assert set(seen) == ({0, 1, 2, 3} if keep_going else {0, 1})
        if not keep_going:
            assert results[2:] == [None, None]

    run(scenario())


@pytest.mark.parametrize("callback_failure", [True, False])
def test_abort_cancels_and_drains_workers(backend, callback_failure):
    async def scenario():
        executor = backend[0](None, concurrency=3, continue_on_error=True)
        workload = work(backend, 4)
        ready, callback_started = asyncio.Event(), asyncio.Event()
        cleaned, seen = [], []
        started = 0
        failure = backend[3]()  # Callback database exceptions must propagate unchanged.

        async def operation(query, **kwargs):
            nonlocal started
            index = next(i for i, e in enumerate(workload) if e.query is query)
            started += 1
            if started == 3:
                ready.set()
            try:
                await ready.wait()
                if index == 0:
                    return ExecutionResult(0)
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.append(index)

        async def callback(index, entry, result):
            seen.append(index)
            callback_started.set()
            if callback_failure:
                raise failure
            await asyncio.Event().wait()

        executor.run = operation
        task = asyncio.create_task(executor.run_workload(workload, on_result=callback))
        await callback_started.wait()
        if not callback_failure:
            task.cancel()
        with pytest.raises(type(failure) if callback_failure else asyncio.CancelledError) as caught:
            await task
        if callback_failure:
            assert caught.value is failure
        assert seen == [0] and sorted(cleaned) == [0, 1, 2]
        assert started == 3

    run(scenario())


def test_callback_failure_drops_queued_deliveries(backend):
    async def scenario():
        executor = backend[0](None, concurrency=2)
        workload = work(backend, 3)
        second_done = asyncio.Event()
        seen = []

        async def operation(query, **kwargs):
            if query is workload[1].query:
                second_done.set()
            return ExecutionResult(0)

        async def callback(index, entry, result):
            seen.append(index)
            await second_done.wait()
            raise ValueError("persistence failed")

        executor.run = operation
        with pytest.raises(ValueError, match="persistence failed"):
            await executor.run_workload(workload, on_result=callback)
        assert seen == [0]

    run(scenario())


@pytest.mark.parametrize("method", METHODS)
def test_invalid_and_empty_callback_inputs(backend, method):
    async def scenario():
        executor = backend[0](None)

        async def forbidden(*args, **kwargs):
            pytest.fail("No operation should start")

        setattr(executor, method, forbidden)
        with pytest.raises(TypeError, match="on_result"):
            await getattr(executor, method + "_workload")(work(backend, 1), on_result=42)
        assert (
            await getattr(executor, method + "_workload")(
                Workload(), on_result=lambda *args: pytest.fail("empty callback")
            )
            == []
        )

    run(scenario())


@pytest.mark.parametrize("method", METHODS)
def test_sync_caller_thread_and_context(backend, method):
    owner = threading.get_ident()
    local = threading.local()
    local.experiment = "active experiment"
    workload = work(backend, 3)
    seen = []
    background = []

    async def factory():
        executor = backend[0](None, concurrency=2)

        async def operation(query, **kwargs):
            background.append(threading.get_ident())
            await asyncio.sleep(0)
            return ExecutionResult(0)

        setattr(executor, method, operation)
        return executor

    def callback(index, entry, result):
        assert threading.get_ident() == owner
        assert local.experiment == "active experiment"
        assert entry is workload[index]
        seen.append((index, result))

    with backend[1]._create(factory) as executor:
        results = getattr(executor, method + "_workload")(workload, on_result=callback)
    assert len(seen) == 3 and all(r is results[i] for i, r in seen)
    assert all(t != owner for t in background)
    assert not executor._worker.is_alive()


@pytest.mark.parametrize("failure_kind", ["ordinary", "database", "awaitable", "reentrant"])
def test_sync_callback_failure_cleanup(backend, failure_kind):
    workload = work(backend, 3)
    cleaned = threading.Event()
    failure = backend[3]() if failure_kind == "database" else ValueError("callback failed")

    async def factory():
        executor = backend[0](None, concurrency=2)
        started = asyncio.Event()

        async def operation(query, **kwargs):
            if query is workload[0].query:
                await started.wait()
                return ExecutionResult(0)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        executor.run = operation
        return executor

    async def coroutine():
        pass

    def callback(*args):
        if failure_kind == "awaitable":
            return coroutine()
        if failure_kind == "reentrant":
            executor.run_workload(Workload())
        raise failure

    expected = (
        TypeError
        if failure_kind == "awaitable"
        else RuntimeError
        if (failure_kind == "reentrant")
        else type(failure)
    )
    with backend[1]._create(factory) as executor:
        with pytest.raises(expected):
            executor.run_workload(workload, on_result=callback)
        assert cleaned.is_set()
        assert executor.run_workload(Workload()) == []
    assert not executor._worker.is_alive()


@pytest.mark.parametrize("method", METHODS)
def test_sync_rejects_async_callback_before_execution(backend, method):
    async def factory():
        executor = backend[0](None)

        async def forbidden(*args, **kwargs):
            pytest.fail("No operation should start")

        setattr(executor, method, forbidden)
        return executor

    async def callback(*args):
        pass

    with backend[1]._create(factory) as executor:
        with pytest.raises(TypeError, match="async callback"):
            getattr(executor, method + "_workload")(work(backend, 1), on_result=callback)
        with pytest.raises(TypeError, match="callable"):
            getattr(executor, method + "_workload")(work(backend, 1), on_result=42)


@pytest.mark.parametrize("in_callback", [False, True])
def test_sync_interrupt_drains_background_workers(backend, in_callback):
    import os
    import signal

    workload = work(backend, 3)
    interrupt_ready = threading.Event()
    cleaned = threading.Event()
    seen = []

    async def factory():
        executor = backend[0](None, concurrency=2)
        second_started = asyncio.Event()

        async def operation(query, **kwargs):
            if query is workload[0].query:
                await second_started.wait()
                if in_callback:
                    return ExecutionResult(0)
            second_started.set()
            if not in_callback:
                interrupt_ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        executor.run = operation
        return executor

    def callback(index, entry, result):
        seen.append(index)
        interrupt_ready.set()
        threading.Event().wait(5)

    def interrupt():
        if interrupt_ready.wait(3):
            os.kill(os.getpid(), signal.SIGINT)

    with backend[1]._create(factory) as executor:
        sender = threading.Thread(target=interrupt)
        sender.start()
        try:
            with pytest.raises(KeyboardInterrupt):
                executor.run_workload(workload, on_result=callback)
        finally:
            sender.join()
        assert cleaned.is_set()
        assert seen == ([0] if in_callback else [])
        assert executor.run_workload(Workload()) == []
    assert not executor._worker.is_alive()


def test_sync_callback_from_notebook_loop(backend):
    async def scenario():
        caller_loop = asyncio.get_running_loop()

        async def factory():
            executor = backend[0](None)

            async def operation(query, **kwargs):
                assert asyncio.get_running_loop() is not caller_loop
                return ExecutionResult(0)

            executor.run = operation
            return executor

        seen = []

        def callback(*args):
            seen.append(asyncio.get_running_loop())

        with backend[1]._create(factory) as executor:
            executor.run_workload(work(backend, 1), on_result=callback)
        assert seen == [caller_loop]

    run(scenario())


@pytest.mark.parametrize("error", [SystemExit("stop"), KeyboardInterrupt()])
def test_async_process_control_callback_errors_cleanup(backend, error):
    async def scenario():
        executor = backend[0](None, concurrency=2)
        workload = work(backend, 2)
        started, cleaned = asyncio.Event(), asyncio.Event()

        async def operation(query, **kwargs):
            if query is workload[0].query:
                await started.wait()
                return ExecutionResult(0)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        def callback(*args):
            raise error

        executor.run = operation
        with pytest.raises(type(error)) as caught:
            await executor.run_workload(workload, on_result=callback)
        assert caught.value is error and cleaned.is_set()

    run(scenario())


def test_sync_system_exit_callback_keeps_loop_usable(backend):
    async def factory():
        executor = backend[0](None)

        async def operation(query, **kwargs):
            return ExecutionResult(0)

        executor.run = operation
        return executor

    def callback(*args):
        raise SystemExit("stop")

    with backend[1]._create(factory) as executor:
        with pytest.raises(SystemExit, match="stop"):
            executor.run_workload(work(backend, 1), on_result=callback)
        assert executor.run_workload(Workload()) == []


def test_programming_error_has_no_synthetic_callback(backend):
    async def scenario():
        executor = backend[0](None, continue_on_error=True)

        async def operation(query, **kwargs):
            raise TypeError("programming error")

        executor.run = operation
        with pytest.raises(TypeError, match="programming error"):
            await executor.run_workload(
                work(backend, 2), on_result=lambda *args: pytest.fail("Invented result")
            )

    run(scenario())
