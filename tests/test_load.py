"""Load generation contracts with controlled async operations and driver boundaries."""

import asyncio
from itertools import islice
from threading import get_ident
from unittest.mock import MagicMock

import pytest
from pymongo.errors import OperationFailure

from bondi._health import _preflight
from bondi.couchbase import AsyncCouchbaseExecutor, CouchbaseExecutor, CouchbaseQuery
from bondi.execution import DatabaseUnavailableError, ExecutionResult
from bondi.load import LoadResult, Sequential, UniformRandom, WeightedRandom
from bondi.mongodb import AsyncMongoExecutor, MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry


def work(backend, count=3):
    if backend == "mongodb":
        queries = [
            MongoFindQuery(MongoCollectionRef("test", "items"), {"n": n}) for n in range(count)
        ]
    else:
        queries = [CouchbaseQuery(f"SELECT {n}") for n in range(count)]
    return Workload([WorkloadEntry(q) for q in queries])


@pytest.fixture(params=["mongodb", "couchbase"])
def executor(request):
    backend = request.param
    if backend == "couchbase":
        pytest.importorskip("couchbase")
    cls = AsyncMongoExecutor if backend == "mongodb" else AsyncCouchbaseExecutor
    instance = cls(MagicMock(), concurrency=2, continue_on_error=True)
    return instance, work(backend)


async def generate(executor, workload, **kwargs):
    options = dict(selection=Sequential(), measurement_seconds=0.04, drain_timeout_seconds=0.1)
    options.update(kwargs)
    return await executor.generate_load(workload, **options)


def test_policy_prefixes_and_independent_streams():
    weights = [1, 0, 3]
    policy = WeightedRandom(weights, seed=42)
    weights[0] = 0  # Construction snapshots user-owned weights.
    first = list(islice(policy._stream(3, 0), 1000))
    assert first == list(islice(policy._stream(3, 0), 1000))
    assert 1 not in first and 650 < first.count(2) < 850
    assert first != list(islice(policy._stream(3, 1), 1000))
    assert list(islice(UniformRandom(42)._stream(3, 0), 100)) == list(
        islice(WeightedRandom([1, 1, 1], 42)._stream(3, 0), 100)
    )
    assert list(islice(Sequential()._stream(3, 0), 8)) == [0, 1, 2, 0, 1, 2, 0, 1]
    assert list(islice(Sequential()._stream(3, 1), 8)) == [0, 1, 2, 0, 1, 2, 0, 1]


@pytest.mark.parametrize("weights", [[], [0, 0], [-1, 1], [float("nan")], [float("inf")], [True]])
def test_invalid_weights(weights):
    with pytest.raises(ValueError):
        WeightedRandom(weights, seed=42)


@pytest.mark.parametrize("seed", [None, True, 1.2, "42"])
def test_invalid_seed(seed):
    with pytest.raises(TypeError):
        UniformRandom(seed)


def test_duration_is_derived():
    result = LoadResult(0, 0, 0, 0, "measurement", 1, 3, True, ExecutionResult(2000))
    assert result.duration == 2
    result.ended_seconds = 4
    assert result.duration == 3


def test_phases_callbacks_and_reuse(executor):
    ex, workload = executor

    async def scenario():
        async def run(query, **kwargs):
            await _preflight(ex)
            await asyncio.sleep(0.004)
            return ExecutionResult(
                4, row_count=1, documents=[1] if kwargs["collect_results"] else None
            )

        ex.run = run
        delivered = []
        result = await generate(
            ex, workload, warmup_seconds=0.02, on_result=delivered.append, collect_results=True
        )
        assert result == delivered and len({r.attempt_id for r in result}) == len(result)
        assert {r.phase_started for r in result} == {"warmup", "measurement"}
        assert all(r.admitted_seconds < 0.06 for r in result)
        assert all(r.query_started and r.result.documents == [1] for r in result)
        assert all(
            r.phase_started == ("warmup" if r.admitted_seconds < 0.02 else "measurement")
            for r in result
        )
        for client in range(2):
            rs = [r for r in result if r.client_id == client]
            assert [r.workload_position for r in rs] == [i % 3 for i in range(len(rs))]
            assert [r.client_sequence for r in rs] == list(range(len(rs)))
        streamed = []
        assert (
            await generate(ex, workload, return_load_results=False, on_result=streamed.append) == []
        )
        assert streamed and all(r.result.documents is None for r in streamed)
        assert all(
            next(r for r in streamed if r.client_id == i).workload_position == 0 for i in range(2)
        )

    asyncio.run(scenario())


def test_more_clients_than_entries_and_drain_expiry(executor):
    ex, workload = executor
    ex.concurrency = 4
    workload = Workload([workload[0]])

    async def scenario():
        cleaned = []

        async def run(query, **kwargs):
            await _preflight(ex)
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.002)
                cleaned.append(True)

        ex.run = run
        delivered = []
        results = await generate(
            ex,
            workload,
            measurement_seconds=0.01,
            drain_timeout_seconds=0.01,
            on_result=delivered.append,
        )
        assert len(results) == len(cleaned) == 4
        assert results == delivered
        assert [r.attempt_id for r in results] == [0, 1, 2, 3]
        assert all(r.result is None and r.stop_reason == "drain_timeout" for r in results)
        assert all(r.ended_seconds >= 0.02 and r.query_started for r in results)
        assert all(r.duration >= 0 for r in results)

    asyncio.run(scenario())


def test_slow_callback_not_relabelled(executor):
    ex, workload = executor
    ex.concurrency = 1

    async def scenario():
        async def run(query, **kwargs):
            await _preflight(ex)
            return ExecutionResult(0, row_count=0)

        async def callback(result):
            await asyncio.sleep(0.04)

        ex.run = run
        results = await generate(
            ex, workload, measurement_seconds=0.01, drain_timeout_seconds=0.01, on_result=callback
        )
        assert len(results) == 1 and results[0].result.status == "success"
        assert results[0].stop_reason is None and results[0].duration < 0.02

    asyncio.run(scenario())


@pytest.mark.parametrize("keep_going", [True, False])
def test_query_timeout_error_policy(executor, keep_going):
    ex, workload = executor
    ex.concurrency = 1
    ex.continue_on_error = keep_going

    async def scenario():
        async def run(query, **kwargs):
            await _preflight(ex)
            await asyncio.sleep(0.002)
            raise TimeoutError("query expired")

        ex.run = run
        results = await generate(ex, workload)
        assert all(r.result.status == "timeout" for r in results)
        if keep_going:
            assert len(results) > 1 and all(r.stop_reason is None for r in results)
        else:
            assert len(results) == 1 and results[0].stop_reason == "query_error"

    asyncio.run(scenario())


def test_health_failure_stops_even_with_continue(executor):
    ex, workload = executor
    ex.health_check_timeout_seconds = 0.01

    async def scenario():
        async def ping(**kwargs):
            raise DatabaseUnavailableError("probe failed")

        async def run(query, **kwargs):
            await _preflight(ex)
            pytest.fail("query must not execute")

        ex.ping = ping
        ex.run = run
        results = await generate(ex, workload, measurement_seconds=1)
        assert len(results) <= 2
        assert sum(r.stop_reason == "database_unavailable" for r in results) == 1
        assert all(not r.query_started and r.result.elapsed_ms == 0 for r in results)

    asyncio.run(scenario())


def test_expiry_during_preflight(executor):
    ex, workload = executor
    ex.health_check_timeout_seconds = 1

    async def scenario():
        async def ping(**kwargs):
            await asyncio.Event().wait()

        async def run(query, **kwargs):
            await _preflight(ex)
            pytest.fail("not reached")

        ex.ping = ping
        ex.run = run
        results = await generate(ex, workload, measurement_seconds=0.01, drain_timeout_seconds=0.01)
        assert all(not r.query_started and r.result is None for r in results)

    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["operation", "callback", "cancel"])
def test_exceptions_and_cancellation_cleanup(executor, source):
    ex, workload = executor

    async def scenario():
        closed = []
        started = asyncio.Event()

        async def run(query, **kwargs):
            try:
                started.set()
                if source == "operation":
                    raise ValueError("bad operation")
                if source == "cancel":
                    await asyncio.Event().wait()
                return ExecutionResult(0)
            finally:
                closed.append(True)

        def callback(result):
            if source == "callback":
                raise RuntimeError("bad callback")

        ex.run = run
        task = asyncio.create_task(generate(ex, workload, on_result=callback))
        await started.wait()
        if source == "cancel":
            task.cancel()
        error = {
            "operation": ValueError,
            "callback": RuntimeError,
            "cancel": asyncio.CancelledError,
        }[source]
        with pytest.raises(error):
            await task
        assert closed
        assert not [
            t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()
        ]

    asyncio.run(scenario())


def test_options_validated_before_execution(executor):
    ex, workload = executor

    async def scenario():
        for options in [
            dict(measurement_seconds=0),
            dict(warmup_seconds=-1),
            dict(drain_timeout_seconds=float("inf")),
            dict(return_load_results=1),
            dict(selection=WeightedRandom([1], 0)),
            dict(on_result=3),
        ]:
            with pytest.raises((TypeError, ValueError)):
                await generate(ex, workload, **options)
        with pytest.raises(ValueError, match="nonempty"):
            await generate(ex, Workload([]))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "sync_cls, async_cls",
    [(MongoExecutor, AsyncMongoExecutor), (CouchbaseExecutor, AsyncCouchbaseExecutor)],
)
def test_sync_callbacks_on_caller_thread(sync_cls, async_cls):
    if async_cls is AsyncCouchbaseExecutor:
        pytest.importorskip("couchbase")
    backend = "mongodb" if async_cls is AsyncMongoExecutor else "couchbase"

    async def factory():
        ex = async_cls(MagicMock(), concurrency=1)

        async def run(query, **kwargs):
            await _preflight(ex)
            await asyncio.sleep(0.001)
            return ExecutionResult(1)

        async def close():
            pass

        ex.run, ex.close = run, close
        return ex

    threads = []
    with sync_cls._create(factory) as ex:
        results = ex.generate_load(
            work(backend),
            selection=Sequential(),
            measurement_seconds=0.01,
            drain_timeout_seconds=0.1,
            on_result=lambda r: threads.append(get_ident()),
        )
    assert results and threads == [get_ident()] * len(results)


def test_mongo_actual_cursor_path():
    from tests.test_executor import Cursor, driver

    async def scenario():
        client, _, collection = driver()
        collection.find.side_effect = lambda **kwargs: Cursor([{"x": 1}])
        ex = AsyncMongoExecutor(client)
        results = await generate(ex, work("mongodb"), collect_results=True)
        assert results and all(
            r.query_started and r.result.documents == [{"x": 1}] for r in results
        )
        collection.find.side_effect = OperationFailure("bad syntax")
        results = await generate(ex, work("mongodb"))
        assert len(results) == 1 and results[0].stop_reason == "query_error"

    asyncio.run(scenario())


def test_suppressed_cancellation_has_one_unresolved_result(executor):
    ex, workload = executor
    ex.concurrency = 1

    async def scenario():
        async def run(query, **kwargs):
            await _preflight(ex)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.002)
                return ExecutionResult(1, row_count=1)

        ex.run = run
        delivered = []
        result = await generate(
            ex,
            workload,
            measurement_seconds=0.01,
            drain_timeout_seconds=0.01,
            on_result=delivered.append,
            return_load_results=False,
        )
        assert result == [] and len(delivered) == 1
        assert delivered[0].result is None and delivered[0].stop_reason == "drain_timeout"

    asyncio.run(scenario())


def test_early_failure_drains_other_client(executor):
    ex, workload = executor
    ex.continue_on_error = False

    async def scenario():
        started = 0

        async def run(query, **kwargs):
            nonlocal started
            await _preflight(ex)
            started += 1
            which = started
            if which == 1:
                await asyncio.sleep(0.005)
                raise TimeoutError("first query failed")
            await asyncio.sleep(0.02)
            return ExecutionResult(20)

        ex.run = run
        results = await generate(ex, workload, measurement_seconds=10)
        assert len(results) == started == 2
        assert results[0].stop_reason == "query_error"
        assert results[1].stop_reason is None and results[1].result.status == "success"
        assert results[1].ended_seconds < 1

    asyncio.run(scenario())


def test_query_timeout_shorter_than_drain_is_completed_outcome(executor):
    ex, workload = executor
    ex.concurrency = 1

    async def scenario():
        async def run(query, **kwargs):
            await _preflight(ex)
            async with asyncio.timeout(0.03):
                await asyncio.Event().wait()

        ex.run = run
        results = await generate(ex, workload, measurement_seconds=0.01, drain_timeout_seconds=0.1)
        assert len(results) == 1
        assert results[0].result.status == "timeout" and results[0].stop_reason is None

    asyncio.run(scenario())


def test_couchbase_actual_streaming_path():
    pytest.importorskip("couchbase")
    from couchbase.exceptions import InvalidArgumentException, ParsingFailedException

    from tests.test_couchbase_executor import Response, cluster

    async def scenario():
        driver = cluster(Response())
        responses = []

        def query(*args):
            response = Response([{"x": 1}])
            responses.append(response)
            return response

        driver.query.side_effect = query
        ex = AsyncCouchbaseExecutor(driver)
        results = await generate(ex, work("couchbase"), collect_results=True)
        assert results and all(
            r.query_started and r.result.documents == [{"x": 1}] for r in results
        )
        assert all(r.cleaned for r in responses)
        driver.query.side_effect = ParsingFailedException("bad syntax")
        results = await generate(ex, work("couchbase"))
        assert len(results) == 1 and results[0].stop_reason == "query_error"
        driver.query.side_effect = InvalidArgumentException("invalid API option")
        with pytest.raises(InvalidArgumentException):
            await generate(ex, work("couchbase"))
        response = Response(block=True)
        driver.query.side_effect = None
        driver.query.return_value = response
        results = await generate(
            ex, work("couchbase"), measurement_seconds=0.01, drain_timeout_seconds=0.01
        )
        assert response.cleaned and results[0].stop_reason == "drain_timeout"

    asyncio.run(scenario())
