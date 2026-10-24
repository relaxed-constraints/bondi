"""Async executor behaviour at the driver boundary, without a database."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pymongo.errors import ExecutionTimeout, OperationFailure

from dbrtoolkit.couchbase import CouchbaseQuery
from dbrtoolkit.execution import ExecutionResult
from dbrtoolkit.mongodb import (
    AsyncMongoDBExecutor,
    MongoAggregateQuery,
    MongoCollectionRef,
    MongoFindQuery,
    summarize_explain,
)
from dbrtoolkit.workload import Workload, WorkloadEntry

TARGET = MongoCollectionRef("research", "businesses")


class Cursor:
    def __init__(self, documents=(), error=None):
        self.documents = iter(documents)
        self.error = error
        self.close = AsyncMock()
        self.consumed = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0)
        try:
            document = next(self.documents)
        except StopIteration:
            if self.error:
                raise self.error
            raise StopAsyncIteration from None
        self.consumed += 1
        return document


def driver(cursor=None):
    client = MagicMock()
    client.close = AsyncMock()
    db = client.__getitem__.return_value
    collection = db.__getitem__.return_value
    collection.find.return_value = cursor or Cursor()
    collection.aggregate = AsyncMock(return_value=cursor or Cursor())
    db.command = AsyncMock(return_value={"ok": 1, "queryPlanner": {}})
    return client, db, collection


def workload(count):
    return Workload([WorkloadEntry(MongoFindQuery(TARGET, {"i": i})) for i in range(count)])


@pytest.mark.parametrize("collect", [False, True])
@pytest.mark.parametrize("aggregate", [False, True])
def test_consumes_all_results_and_routes_options(collect, aggregate):
    async def scenario():
        cursor = Cursor([{"x": 1}, {"x": 2}])
        client, _, collection = driver(cursor)
        query = (
            MongoAggregateQuery(TARGET, [{"$limit": 2}])
            if aggregate
            else MongoFindQuery(TARGET, {"x": 1}, {"x": 1}, (("x", -1),), 1, 2)
        )
        result = await AsyncMongoDBExecutor(client).run(
            query, collect_results=collect, query_kwargs={"comment": "test"}
        )
        assert result.row_count == cursor.consumed == 2
        assert result.documents == ([{"x": 1}, {"x": 2}] if collect else None)
        assert result.status == "success" and result.elapsed_ms >= 0
        cursor.close.assert_awaited_once()
        if aggregate:
            collection.aggregate.assert_awaited_once_with(query.pipeline, comment="test")
        else:
            collection.find.assert_called_once_with(
                filter={"x": 1},
                projection={"x": 1},
                sort=[("x", -1)],
                skip=1,
                limit=2,
                comment="test",
            )

    asyncio.run(scenario())


def test_cursor_failure_closes_and_single_run_raises():
    async def scenario():
        error = OperationFailure("failed")
        cursor = Cursor([{"x": 1}], error)
        client, _, _ = driver(cursor)
        with pytest.raises(OperationFailure) as caught:
            await AsyncMongoDBExecutor(client).run(MongoFindQuery(TARGET, {}), collect_results=True)
        assert caught.value is error
        cursor.close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize("aggregate", [False, True])
def test_explain_command_routing(aggregate):
    async def scenario():
        client, db, _ = driver()
        query = (
            MongoAggregateQuery(TARGET, [])
            if aggregate
            else MongoFindQuery(TARGET, {}, sort=(("b", -1), ("a", 1)), limit=5)
        )
        result = await AsyncMongoDBExecutor(client).explain(
            query,
            verbosity="executionStats",
            query_kwargs={"hint": "idx"},
            command_kwargs={"maxTimeMS": 100},
        )
        command = db.command.call_args.args[0]
        assert command["verbosity"] == "executionStats"
        assert command["explain"]["hint"] == "idx"
        assert db.command.call_args.kwargs == {"maxTimeMS": 100}
        if aggregate:
            assert command["explain"]["pipeline"] == []
            assert command["explain"]["cursor"] == {}
        else:
            assert list(command["explain"]["sort"]) == ["b", "a"]
            assert command["explain"]["limit"] == 5
        assert result.raw == {"ok": 1, "queryPlanner": {}}
        assert result.row_count is result.documents is None

    asyncio.run(scenario())


def test_sequential_failure_policies_and_partial_results():
    async def scenario(keep_going):
        client, _, collection = driver()
        error = ExecutionTimeout("slow", code=50)
        cursors = [Cursor([{"x": 1}]), Cursor([{"x": 2}], error), Cursor()]
        collection.find.side_effect = cursors
        results = await AsyncMongoDBExecutor(client, continue_on_error=keep_going).run_workload(
            workload(3), collect_results=True
        )
        assert results[0].status == "success"
        assert results[1].status == "timeout"
        assert results[1].error is error
        assert results[1].row_count is results[1].documents is None
        assert (results[2] is not None) == keep_going

    asyncio.run(scenario(False))
    asyncio.run(scenario(True))


def test_parallel_stop_drains_inflight_and_preserves_positions():
    async def scenario():
        client, _, _ = driver()
        executor = AsyncMongoDBExecutor(client, concurrency=2)
        started = []
        second_started = asyncio.Event()
        first_finished = asyncio.Event()

        async def run(query, **kwargs):
            i = query.filter["i"]
            started.append(i)
            if i == 0:
                await second_started.wait()
                first_finished.set()
                raise OperationFailure("bad query")
            second_started.set()
            await first_finished.wait()
            await asyncio.sleep(0)
            return ExecutionResult(1, row_count=i)

        executor.run = run
        results = await executor.run_workload(workload(5))
        assert started == [0, 1]
        assert results[0].status == "error"
        assert results[1].row_count == 1
        assert results[2:] == [None, None, None]

    asyncio.run(scenario())


def test_parallel_continue_bounds_active_workers_and_attempts_each_entry():
    async def scenario():
        client, _, _ = driver()
        executor = AsyncMongoDBExecutor(client, concurrency=3, continue_on_error=True)
        active = peak = 0

        async def run(query, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            if query.filter["i"] == 2:
                raise OperationFailure("failure")
            return ExecutionResult(1, row_count=query.filter["i"])

        executor.run = run
        results = await executor.run_workload(workload(9))
        assert peak == 3
        assert results[2].status == "error"
        assert [r.row_count for i, r in enumerate(results) if i != 2] == [0, 1, 3, 4, 5, 6, 7, 8]

    asyncio.run(scenario())


def test_cancellation_closes_active_cursor():
    async def scenario():
        entered = asyncio.Event()

        class Blocking(Cursor):
            async def __anext__(self):
                entered.set()
                await asyncio.Event().wait()

        cursor = Blocking()
        client, _, _ = driver(cursor)
        task = asyncio.create_task(AsyncMongoDBExecutor(client).run_workload(workload(2)))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        cursor.close.assert_awaited_once()

    asyncio.run(scenario())


def test_programming_error_propagates_and_cleans_workers():
    async def scenario():
        client, _, _ = driver()
        executor = AsyncMongoDBExecutor(client, concurrency=2, continue_on_error=True)
        entered = asyncio.Event()
        cleaned = asyncio.Event()

        async def run(query, **kwargs):
            if query.filter["i"] == 0:
                await entered.wait()
                raise TypeError("bug")
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        executor.run = run
        with pytest.raises(TypeError, match="bug"):
            await executor.run_workload(workload(2))
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_borrowed_and_owned_client_lifetimes():
    async def scenario():
        client, _, _ = driver()
        async with AsyncMongoDBExecutor(client):
            pass
        client.close.assert_not_awaited()
        with patch("dbrtoolkit.mongodb.executor.AsyncMongoClient", return_value=client) as factory:
            async with AsyncMongoDBExecutor.from_uri(
                "mongodb://example", client_kwargs={"retryReads": False}
            ) as executor:
                factory.assert_called_once_with("mongodb://example", retryReads=False)
            await executor.close()
            client.close.assert_awaited_once()
            with pytest.raises(RuntimeError, match="closed"):
                await executor.run(MongoFindQuery(TARGET, {}))

    asyncio.run(scenario())


def test_preflight_checks_every_entry_before_io():
    async def scenario():
        client, _, collection = driver()
        executor = AsyncMongoDBExecutor(client)
        work = workload(2)
        work[1].query.limit = -1
        with pytest.raises(ValueError):
            await executor.run_workload(work)
        collection.find.assert_not_called()
        with pytest.raises(TypeError):
            await executor.run_workload(Workload([WorkloadEntry(CouchbaseQuery("SELECT 1"))]))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "options", [{"filter": {}}, {"pipeline": []}, {"limit": 5}, {"$db": "other"}]
)
def test_reserved_query_options_rejected(options):
    async def scenario():
        client, db, collection = driver()
        executor = AsyncMongoDBExecutor(client)
        with pytest.raises(ValueError):
            await executor.run_workload(workload(1), query_kwargs=options)
        with pytest.raises(ValueError):
            await executor.explain_workload(workload(1), query_kwargs=options)
        collection.find.assert_not_called()
        db.command.assert_not_called()

    asyncio.run(scenario())


def test_explain_workload_and_empty_workload():
    async def scenario():
        client, db, _ = driver()
        executor = AsyncMongoDBExecutor(client, continue_on_error=True)
        db.command.side_effect = [{"ok": 1}, OperationFailure("bad")]
        results = await executor.explain_workload(workload(2))
        assert results[0].raw == {"ok": 1}
        assert results[1].status == "error"
        assert await executor.run_workload(Workload()) == []
        with pytest.raises(ValueError):
            await executor.explain_workload(workload(1), command_kwargs={"check": False})
        with pytest.raises(ValueError):
            await executor.explain_workload(workload(1), verbosity="invalid")

    asyncio.run(scenario())


def test_timeout_scope_covers_all_batches():
    async def scenario():
        inside = False

        class Deadline:
            def __enter__(self):
                nonlocal inside
                inside = True

            def __exit__(self, *args):
                nonlocal inside
                inside = False

        class Checked(Cursor):
            async def __anext__(self):
                assert inside
                return await super().__anext__()

        cursor = Checked([{}, {}])
        client, _, _ = driver(cursor)
        with patch(
            "dbrtoolkit.mongodb.executor.pymongo.timeout", return_value=Deadline()
        ) as timeout:
            await AsyncMongoDBExecutor(client, timeout_seconds=5).run(MongoFindQuery(TARGET, {}))
            timeout.assert_called_once_with(5)
        assert not inside

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"concurrency": 0},
        {"concurrency": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"continue_on_error": 1},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises((ValueError, TypeError)):
        AsyncMongoDBExecutor(MagicMock(), **kwargs)


def test_result_status():
    assert ExecutionResult(1).status == "success"
    assert ExecutionResult(1, error=TimeoutError()).status == "timeout"
    assert ExecutionResult(1, error=OperationFailure("bad")).status == "error"


def test_explain_preserves_raw_without_implicit_parsing():
    async def scenario():
        client, db, _ = driver()
        raw = {"ok": 1, "queryPlanner": {"winningPlan": {"stage": 42}}}
        db.command.return_value = raw
        result = await AsyncMongoDBExecutor(client).explain(MongoFindQuery(TARGET, {}))
        assert result.raw is raw
        assert result.status == "success"
        assert result.warnings == ()
        with pytest.raises(ValueError):
            summarize_explain(result.raw)
        assert result.status == "success"
        assert result.raw is raw

    asyncio.run(scenario())
