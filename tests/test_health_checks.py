"""Health checks at driver boundaries, with real scheduler/callback behavior."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import ConnectionFailure, ExecutionTimeout, OperationFailure

from bondi.execution import DatabaseUnavailableError, ExecutionResult
from bondi.mongodb import AsyncMongoExecutor
from tests.test_executor import driver, workload


@pytest.fixture(params=["mongodb", "couchbase"])
def backend(request):
    if request.param == "mongodb":
        client, db, _ = driver()
        client.admin.command = AsyncMock(return_value={"ok": 1})
        return AsyncMongoExecutor, client, workload, client.admin.command
    pytest.importorskip("couchbase")
    from couchbase.diagnostics import PingState, ServiceType

    from bondi.couchbase import AsyncCouchbaseExecutor
    from tests.test_couchbase_executor import Response, cluster
    from tests.test_couchbase_executor import workload as cb_workload

    client = cluster(Response([{}]))
    client.ping = AsyncMock(
        return_value=SimpleNamespace(
            endpoints={ServiceType.Query: [SimpleNamespace(state=PingState.OK)]}
        )
    )
    return AsyncCouchbaseExecutor, client, cb_workload, client.ping


@pytest.mark.parametrize("value", [0, -1, True, "5", float("inf"), float("nan")])
def test_invalid_deadlines(backend, value):
    cls, client, _, probe = backend
    with pytest.raises(ValueError):
        cls(client, health_check_timeout_seconds=value)

    async def scenario():
        with pytest.raises(ValueError):
            await cls(client).ping(timeout_seconds=value)

    asyncio.run(scenario())
    probe.assert_not_called()


@pytest.mark.parametrize("method", ["run", "explain", "profile"])
@pytest.mark.parametrize("enabled", [False, True])
def test_opt_in_single_probe_and_timing(backend, method, enabled):
    cls, client, work, probe = backend

    async def scenario():
        executor = cls(client, health_check_timeout_seconds=1 if enabled else None)
        result = await getattr(executor, method)(work(1)[0].query)
        assert probe.await_count == int(enabled)
        assert result.health_check_elapsed_ms >= 0
        if not enabled:
            assert result.health_check_elapsed_ms == 0
        await executor.close()
        client.close.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["run_workload", "explain_workload", "profile_workload"])
def test_failed_probe_stops_and_delivers_callback(backend, method):
    cls, client, work, probe = backend

    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()

    probe.side_effect = blocked

    async def scenario():
        executor = cls(
            client, timeout_seconds=600, health_check_timeout_seconds=0.02, continue_on_error=True
        )
        callbacks = []
        start = time.monotonic()
        result = await getattr(executor, method)(
            work(4), on_result=lambda i, e, r: callbacks.append((i, r))
        )
        assert time.monotonic() - start < 1
        assert isinstance(result[0].error, DatabaseUnavailableError)
        assert isinstance(result[0].error.__cause__, TimeoutError)
        assert result[0].status == "error"
        assert result[0].elapsed_ms == 0
        assert result[0].health_check_elapsed_ms >= 10
        assert result[1:] == [None] * 3
        assert callbacks == [(0, result[0])]
        assert probe.await_count == 1

    asyncio.run(scenario())


def test_probe_cancellation_keeps_borrowed_client(backend):
    cls, client, _, probe = backend

    async def scenario():
        started = asyncio.Event()
        finished = asyncio.Event()

        async def blocked(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        probe.side_effect = blocked
        task = asyncio.create_task(cls(client).ping())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
        client.close.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("kind", ["connection", "query", "timeout", "auth"])
def test_failure_classification(backend, enabled, kind):
    cls, client, work, _ = backend
    if cls is AsyncMongoExecutor:
        errors = {
            "connection": ConnectionFailure("offline"),
            "query": OperationFailure("syntax", 2),
            "timeout": ExecutionTimeout("limit", 50),
            "auth": OperationFailure("denied", 13),
        }
    else:
        from couchbase.exceptions import (
            AuthenticationException,
            ParsingFailedException,
            ServiceUnavailableException,
            UnAmbiguousTimeoutException,
        )

        errors = {
            "connection": ServiceUnavailableException(),
            "query": ParsingFailedException(),
            "timeout": UnAmbiguousTimeoutException(),
            "auth": AuthenticationException(),
        }

    async def scenario():
        executor = cls(
            client, continue_on_error=True, health_check_timeout_seconds=1 if enabled else None
        )
        error = errors[kind]
        executor.run = AsyncMock(side_effect=error)
        results = await executor.run_workload(work(3))
        stops = enabled and kind in ("connection", "auth")
        assert (results[1] is None) == stops
        if enabled and kind == "connection":
            assert isinstance(results[0].error, DatabaseUnavailableError)
            assert results[0].error.__cause__ is error
        else:
            assert results[0].error is error

    asyncio.run(scenario())


def test_concurrent_failure_drains_callbacks(backend):
    cls, client, work, _ = backend

    async def scenario():
        executor = cls(
            client, concurrency=2, continue_on_error=True, health_check_timeout_seconds=1
        )
        started = asyncio.Event()
        callbacks = []
        calls = 0

        async def operation(query, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                await started.wait()
                raise DatabaseUnavailableError("offline")
            started.set()
            await asyncio.sleep(0.02)
            return ExecutionResult(20)

        executor.run = operation
        result = await executor.run_workload(work(5), on_result=lambda i, e, r: callbacks.append(i))
        assert calls == 2
        assert callbacks == [0, 1]
        assert result[1].status == "success"
        assert result[2:] == [None] * 3

    asyncio.run(scenario())


def test_couchbase_report_requires_query_endpoints():
    pytest.importorskip("couchbase")
    from couchbase.diagnostics import PingState, ServiceType

    from bondi.couchbase import AsyncCouchbaseExecutor
    from tests.test_couchbase_executor import Response, cluster

    async def scenario():
        client = cluster(Response())
        for endpoints in (
            {},
            {ServiceType.KeyValue: [SimpleNamespace(state=PingState.OK)]},
            {ServiceType.Query: [SimpleNamespace(state=PingState.TIMEOUT)]},
        ):
            client.ping = AsyncMock(return_value=SimpleNamespace(endpoints=endpoints))
            with pytest.raises(DatabaseUnavailableError):
                await AsyncCouchbaseExecutor(client).ping(timeout_seconds=0.1)
            options = client.ping.call_args.args[0]
            assert options["service_types"] == [ServiceType.Query]
            assert options["timeout"].total_seconds() == 0.1

    asyncio.run(scenario())


def test_probe_overhead_excluded_from_failed_query(backend):
    cls, client, work, probe = backend
    original = probe.return_value

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.04)
        return original

    probe.side_effect = slow

    async def scenario():
        executor = cls(client, health_check_timeout_seconds=1)
        if cls is AsyncMongoExecutor:
            client.__getitem__.return_value.command.side_effect = OperationFailure("syntax", 2)
        else:
            from couchbase.exceptions import ParsingFailedException

            client.query.side_effect = ParsingFailedException()
        result = (await executor.explain_workload(work(1)))[0]
        assert result.health_check_elapsed_ms >= 30
        assert result.elapsed_ms < result.health_check_elapsed_ms

    asyncio.run(scenario())


def test_invalid_query_does_not_probe(backend):
    cls, client, _, probe = backend

    async def scenario():
        with pytest.raises(TypeError):
            await cls(client, health_check_timeout_seconds=1).run(object())
        probe.assert_not_called()

    asyncio.run(scenario())


def test_callback_failure_cancels_other_probe(backend):
    cls, client, work, probe = backend

    async def scenario():
        executor = cls(client, concurrency=2, health_check_timeout_seconds=1)
        both_started = asyncio.Event()
        cancelled = asyncio.Event()
        count = 0

        async def probing(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                await both_started.wait()
                raise DatabaseUnavailableError("offline")
            both_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        probe.side_effect = probing

        def callback(*args):
            raise LookupError("checkpoint failed")

        with pytest.raises(LookupError, match="checkpoint"):
            await executor.run_workload(work(4), on_result=callback)
        assert cancelled.is_set()

    asyncio.run(scenario())


def test_real_mongo_probe_overrides_long_borrowed_timeouts():
    """A bound but non-listening port is unavailable without touching a database."""
    import socket

    from pymongo import AsyncMongoClient

    async def scenario(port):
        client = AsyncMongoClient(
            f"mongodb://127.0.0.1:{port}",
            serverSelectionTimeoutMS=600000,
            connectTimeoutMS=600000,
            timeoutMS=600000,
        )
        try:
            executor = AsyncMongoExecutor(client, timeout_seconds=600)
            start = time.monotonic()
            with pytest.raises(DatabaseUnavailableError):
                await executor.ping(timeout_seconds=0.05)
            assert time.monotonic() - start < 1
            await executor.close()
            assert not client._closed
        finally:
            await client.close()

    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        asyncio.run(scenario(reserved.getsockname()[1]))


def test_probe_has_separate_execution_budget(backend):
    cls, client, work, probe = backend
    healthy = probe.return_value

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.04)
        return healthy

    probe.side_effect = slow

    async def scenario():
        executor = cls(client, timeout_seconds=0.02, health_check_timeout_seconds=0.2)
        result = await executor.run(work(1)[0].query)
        assert result.status == "success"
        assert result.health_check_elapsed_ms >= 30
        assert result.elapsed_ms < result.health_check_elapsed_ms

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["auth", "configuration"])
def test_probe_preserves_access_and_configuration_errors(backend, kind):
    cls, client, work, probe = backend
    if cls is AsyncMongoExecutor:
        from pymongo.errors import ConfigurationError

        error = OperationFailure("auth", 18) if kind == "auth" else ConfigurationError("bad")
    else:
        from couchbase.exceptions import AuthenticationException, InvalidArgumentException

        error = AuthenticationException() if kind == "auth" else InvalidArgumentException()
    probe.side_effect = error

    async def scenario():
        executor = cls(client, health_check_timeout_seconds=1, continue_on_error=True)
        with pytest.raises(type(error)) as caught:
            await executor.ping()
        assert caught.value is error
        if kind == "auth":
            result = await executor.run_workload(work(2))
            assert result[0].error is error
            assert result[0].elapsed_ms == 0
            assert result[1] is None
        else:
            with pytest.raises(type(error)):
                await executor.run_workload(work(2))

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["run_workload", "explain_workload", "profile_workload"])
def test_healthy_workload_probes_once_per_entry(backend, method):
    cls, client, work, probe = backend

    async def scenario():
        executor = cls(client, health_check_timeout_seconds=1, concurrency=2)
        results = await getattr(executor, method)(work(3))
        assert all(result.status == "success" for result in results)
        assert probe.await_count == 3

    asyncio.run(scenario())
