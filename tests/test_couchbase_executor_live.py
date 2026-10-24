"""Opt-in read-only checks against the initialized Compose demo collection."""

import asyncio
import json
import os

import pytest

pytest.importorskip("couchbase")
from couchbase.exceptions import ParsingFailedException  # noqa: E402
from couchbase.n1ql import QueryScanConsistency  # noqa: E402

from dbrtoolkit.couchbase import (  # noqa: E402
    AsyncCouchbaseExecutor,
    CouchbaseQuery,
    summarize,
)
from dbrtoolkit.workload import Workload, WorkloadEntry  # noqa: E402


@pytest.mark.parametrize("edition", ["COMMUNITY", "ENTERPRISE"])
def test_live_couchbase(edition):
    uri = os.environ.get(f"DBRTOOLKIT_TEST_COUCHBASE_{edition}_URI")
    if not uri:
        pytest.skip(f"Set DBRTOOLKIT_TEST_COUCHBASE_{edition}_URI to opt in")

    async def scenario():
        async with await AsyncCouchbaseExecutor.from_uri(
            uri,
            username=os.environ["DBRTOOLKIT_TEST_COUCHBASE_USERNAME"],
            password=os.environ["DBRTOOLKIT_TEST_COUCHBASE_PASSWORD"],
            concurrency=2,
            continue_on_error=True,
            timeout_seconds=10,
        ) as executor:
            query = CouchbaseQuery(
                "SELECT RAW b.name FROM business b WHERE city = $city ORDER BY b.name",
                named_parameters={"city": "Sydney"},
                query_context="demo._default",
            )
            options = {"read_only": True, "scan_consistency": QueryScanConsistency.REQUEST_PLUS}
            run = await executor.run(query, collect_results=True, query_kwargs=options)
            assert run.documents == ["Garden Books", "Harbour Cafe", "Station Noodles"]
            assert run.row_count == run.raw["metrics"]["result_count"] == 3
            assert run.raw["profile"] is None
            plan = await executor.explain(query, query_kwargs=options)
            assert isinstance(plan.raw["plan"], dict)
            assert plan.row_count is plan.documents is None
            profile = await executor.profile(query, collect_results=True, query_kwargs=options)
            assert profile.documents == run.documents
            assert profile.raw["metrics"]["execution_ms"] >= 0
            if edition == "ENTERPRISE":
                assert profile.raw["profile"]["executionTimings"]
                assert profile.warnings == ()
            else:
                assert profile.raw["profile"] is None
                assert "executionTimings" in profile.warnings[-1]
            assert summarize(plan.raw).index_names == ("city_stars",)
            assert summarize(run.raw).rows_returned == 3
            summary = summarize(profile.raw)
            assert summary.rows_returned == 3
            assert summary.index_names == (("city_stars",) if edition == "ENTERPRISE" else None)
            assert summary.documents_examined is summary.keys_examined is None
            json.dumps(profile.raw)
            positional = CouchbaseQuery("SELECT RAW $1", positional_parameters=[[1, None]])
            work = Workload([WorkloadEntry(query), WorkloadEntry(positional)])
            for method in (
                executor.run_workload,
                executor.explain_workload,
                executor.profile_workload,
            ):
                results = await method(work, query_kwargs=options)
                assert [r.status for r in results] == ["success", "success"]
            rows = await executor.run(positional, collect_results=True, query_kwargs=options)
            assert rows.documents == [[1, None]]
            bad = Workload([WorkloadEntry(CouchbaseQuery("INVALID SQL")), WorkloadEntry(query)])
            results = await executor.run_workload(bad, query_kwargs=options)
            assert isinstance(results[0].error, ParsingFailedException)
            assert results[1].row_count == 3
            executor.concurrency = 1
            executor.continue_on_error = False
            results = await executor.profile_workload(bad, query_kwargs=options)
            assert results[0].status == "error" and results[1] is None
            # Read-only, collection-free workload forces an SDK/server deadline.
            executor.timeout_seconds = 0.001
            slow = CouchbaseQuery("SELECT RAW SUM(x) FROM ARRAY_RANGE(0, 1000000) AS x")
            results = await executor.run_workload(
                Workload([WorkloadEntry(slow)]), query_kwargs=options
            )
            assert results[0].status == "timeout", repr(results[0].error)

    asyncio.run(scenario())
