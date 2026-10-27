"""SDK-boundary checks without a running database; install the couchbase extra."""

import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("couchbase")
from couchbase.exceptions import (  # noqa: E402
    InvalidArgumentException,
    ParsingFailedException,
    UnAmbiguousTimeoutException,
)
from couchbase.n1ql import QueryProfile, QueryScanConsistency  # noqa: E402

from bondi.couchbase import AsyncCouchbaseExecutor, CouchbaseQuery  # noqa: E402
from bondi.execution import ExecutionResult  # noqa: E402
from bondi.mongodb import MongoCollectionRef, MongoFindQuery  # noqa: E402
from bondi.workload import Workload, WorkloadEntry  # noqa: E402


def workload(count):
    return Workload([WorkloadEntry(CouchbaseQuery(f"SELECT {i}")) for i in range(count)])


def metadata(profile=None, warnings=()):
    meta = MagicMock()
    meta.request_id.return_value = "request"
    meta.client_context_id.return_value = "context"
    meta.status.return_value.value = "success"
    meta.signature.return_value = None
    meta.profile.return_value = profile
    meta.warnings.return_value = warnings
    metrics = meta.metrics.return_value
    metrics.elapsed_time.return_value = timedelta(milliseconds=2)
    metrics.execution_time.return_value = timedelta(milliseconds=1)
    for name in (
        "result_count",
        "result_size",
        "sort_count",
        "mutation_count",
        "error_count",
        "warning_count",
    ):
        getattr(metrics, name).return_value.value = 0
    return meta


class Response:
    def __init__(self, rows=(), meta=None, error=None, block=False):
        self.values = rows
        self.meta = meta or metadata()
        self.error = error
        self.block = block
        self.consumed = 0
        self.finished = False
        self.cleaned = False

    async def rows(self):
        try:
            for row in self.values:
                await asyncio.sleep(0)
                self.consumed += 1
                yield row
            if self.block:
                await asyncio.Event().wait()
            if self.error:
                raise self.error
            self.finished = True
        finally:
            self.cleaned = True

    def metadata(self):
        assert self.finished
        return self.meta


def cluster(response):
    c = MagicMock()
    c.query.return_value = response
    c.close = AsyncMock()
    c.wait_until_ready = AsyncMock()
    return c


@pytest.mark.parametrize("method", ["run", "profile"])
@pytest.mark.parametrize("collect", [True, False])
def test_consume_rows_bindings_metadata(method, collect):
    async def scenario():
        response = Response([{"x": 1}, 42, [1, 2], None], metadata({"executionTimings": {"x": 1}}))
        c = cluster(response)
        q = CouchbaseQuery(
            "SELECT RAW $x", named_parameters={"x": 3}, query_context="demo._default"
        )
        r = await getattr(AsyncCouchbaseExecutor(c, timeout_seconds=4), method)(
            q,
            collect_results=collect,
            query_kwargs={"scan_consistency": QueryScanConsistency.REQUEST_PLUS, "read_only": True},
        )
        assert r.row_count == response.consumed == 4
        assert r.documents == (response.values if collect else None)
        assert r.raw["metrics"]["execution_ms"] == 1
        json.dumps(r.raw)
        statement, options = c.query.call_args.args
        assert statement == q.statement
        assert options["named_parameters"] == {"x": 3}
        assert options["query_context"] == "demo._default"
        assert options["timeout"] == timedelta(seconds=4)
        assert options["profile"] == (
            QueryProfile.TIMINGS if method == "profile" else QueryProfile.OFF
        )
        assert options["metrics"] is True
        assert options["scan_consistency"] == QueryScanConsistency.REQUEST_PLUS
        c.query.assert_called_once()

    asyncio.run(scenario())


def test_explain_plan_and_positional_parameters():
    async def scenario():
        plan = {"plan": {"#operator": "Sequence"}}
        c = cluster(Response([plan]))
        r = await AsyncCouchbaseExecutor(c).explain(
            CouchbaseQuery("SELECT $1", positional_parameters=[5])
        )
        assert r.raw is plan
        assert r.row_count is r.documents is None
        assert c.query.call_args.args[0] == "EXPLAIN SELECT $1"
        assert c.query.call_args.args[1]["positional_parameters"] == [5]

    asyncio.run(scenario())


def test_community_profile_warning_and_native_warning():
    async def scenario():
        warning = SimpleNamespace(code=lambda: 123, message=lambda: "example")
        c = cluster(Response([1], metadata(warnings=[warning])))
        r = await AsyncCouchbaseExecutor(c).profile(CouchbaseQuery("SELECT RAW 1"))
        assert r.status == "success"
        assert r.warnings[0] == "123: example"
        assert "executionTimings" in r.warnings[1]
        assert r.raw["profile"] is None
        assert r.raw["warnings"] == [{"code": 123, "message": "example"}]

    asyncio.run(scenario())


@pytest.mark.parametrize("method", ["run_workload", "explain_workload", "profile_workload"])
@pytest.mark.parametrize("keep_going", [True, False])
def test_error_policy_discards_partial_results(method, keep_going):
    async def scenario():
        error = UnAmbiguousTimeoutException("slow")
        c = cluster(None)
        c.query.side_effect = [Response([1], error=error), Response([{"plan": {}}])]
        results = await getattr(AsyncCouchbaseExecutor(c, continue_on_error=keep_going), method)(
            workload(2)
        )
        assert results[0].error is error
        assert results[0].status == "timeout"
        assert results[0].documents is results[0].row_count is results[0].raw is None
        if keep_going:
            assert results[1].status == "success"
        else:
            assert results[1] is None
        assert c.query.call_count == (2 if keep_going else 1)

    asyncio.run(scenario())


def test_validation_before_work_and_single_error_propagation():
    async def scenario():
        c = cluster(Response())
        e = AsyncCouchbaseExecutor(c)
        for method in (e.run_workload, e.explain_workload, e.profile_workload):
            for key in (
                "statement",
                "profile",
                "metrics",
                "timeout",
                "raw",
                "named_parameters",
                "serializer",
            ):
                with pytest.raises(ValueError):
                    await method(workload(1), query_kwargs={key: None})
        invalid = workload(2)
        invalid[1].query.statement = " "
        with pytest.raises(ValueError):
            await e.run_workload(invalid)
        with pytest.raises(TypeError):
            await e.run_workload(
                Workload([WorkloadEntry(MongoFindQuery(MongoCollectionRef("a", "b"), {}))])
            )
        c.query.assert_not_called()
        error = ParsingFailedException("invalid SQL")
        c.query.return_value = Response(error=error)
        with pytest.raises(ParsingFailedException) as caught:
            await e.run(CouchbaseQuery("INVALID"))
        assert caught.value is error
        c.query.return_value = Response(error=InvalidArgumentException("bad options"))
        with pytest.raises(InvalidArgumentException):
            await e.run_workload(workload(1))

    asyncio.run(scenario())


def test_deadline_and_cancellation_cleanup():
    async def scenario():
        response = Response([1], block=True)
        c = cluster(response)
        e = AsyncCouchbaseExecutor(c, timeout_seconds=0.01)
        results = await e.run_workload(workload(1))
        assert results[0].status == "timeout"
        assert response.cleaned
        response = Response(block=True)
        c.query.return_value = response
        task = asyncio.create_task(AsyncCouchbaseExecutor(c).run_workload(workload(1)))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert response.cleaned

    asyncio.run(scenario())


def test_bounded_concurrency_order_and_drain():
    async def scenario():
        e = AsyncCouchbaseExecutor(cluster(Response()), concurrency=2)
        active = peak = 0
        started = []

        async def run(q, **kwargs):
            nonlocal active, peak
            i = int(q.statement.split()[-1])
            started.append(i)
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01 if i == 0 else 0.02)
                if i == 0:
                    raise ParsingFailedException("bad")
                return ExecutionResult(1, row_count=i)
            finally:
                active -= 1

        e.run = run
        results = await e.run_workload(workload(5))
        assert peak == 2 and active == 0
        assert started == [0, 1]
        assert results[0].status == "error" and results[1].row_count == 1
        assert results[2:] == [None] * 3
        assert await e.run_workload(workload(0)) == []

    asyncio.run(scenario())


def test_owned_borrowed_lifetimes_and_readiness_failure():
    async def scenario():
        c = cluster(Response())
        async with AsyncCouchbaseExecutor(c):
            pass
        c.close.assert_not_awaited()
        with patch("acouchbase.cluster.Cluster.connect", AsyncMock(return_value=c)):
            e = await AsyncCouchbaseExecutor.from_uri(
                "couchbase://local", username="u", password="p"
            )
            c.wait_until_ready.assert_awaited_once()
            await e.close()
            await e.close()
            c.close.assert_awaited_once()
            with pytest.raises(RuntimeError):
                await e.run(CouchbaseQuery("SELECT 1"))
            c.close.reset_mock()
            c.wait_until_ready.side_effect = RuntimeError("not ready")
            with pytest.raises(RuntimeError, match="not ready"):
                await AsyncCouchbaseExecutor.from_uri(
                    "couchbase://local", username="u", password="p"
                )
            c.close.assert_awaited_once()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "error_name",
    [
        "TimeoutException",
        "AmbiguousTimeoutException",
        "UnAmbiguousTimeoutException",
    ],
)
def test_sdk_timeout_variants(error_name):
    from couchbase import exceptions

    error = getattr(exceptions, error_name)("deadline")
    assert ExecutionResult(1, error=error).status == "timeout"


@pytest.mark.parametrize(
    "options",
    [
        {"concurrency": 0},
        {"concurrency": True},
        {"continue_on_error": 1},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 0},
    ],
)
def test_invalid_config_does_not_connect(options):
    async def scenario():
        with patch("acouchbase.cluster.Cluster.connect", AsyncMock()) as connect:
            with pytest.raises((TypeError, ValueError)):
                await AsyncCouchbaseExecutor.from_uri(
                    "couchbase://local", username="u", password="p", **options
                )
            connect.assert_not_awaited()

    asyncio.run(scenario())
