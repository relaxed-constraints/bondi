"""Opt-in read-only Docker smoke tests from an already-running caller loop."""

import asyncio
from threading import Event

import pytest

from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry
from tests._interrupt import interrupt_sync_wait

pytestmark = pytest.mark.live


@pytest.mark.parametrize("backend", ["mongo", "community", "enterprise"])
def test_notebook_live(backend, live_deployments, monkeypatch):
    db = live_deployments("mongodb" if backend == "mongo" else backend)

    async def notebook():
        if backend == "mongo":
            executor = MongoExecutor.from_connection(
                db.connection, concurrency=2, timeout_seconds=10
            )
            query = MongoFindQuery(MongoCollectionRef("demo", "business"), {}, limit=3)
        else:
            executor = CouchbaseExecutor.from_connection(
                db.connection,
                concurrency=2,
                timeout_seconds=10,
            )
            query = CouchbaseQuery("SELECT RAW b FROM demo._default.business b LIMIT 3")
        try:
            assert executor._loop is not asyncio.get_running_loop()
            # Direct SDK access uses the synchronous handle, alongside async-backed execution.
            if backend == "mongo":
                assert executor.client.demo.business.count_documents({}) == 8
                assert executor.client is executor.client
            else:
                rows = executor.cluster.query(
                    "SELECT RAW COUNT(*) FROM demo._default.business"
                ).rows()
                assert list(rows) == [8]
                assert executor.cluster is executor.cluster
            workload = Workload([WorkloadEntry(query), WorkloadEntry(query)])
            for method in (
                "run",
                "explain",
                "profile",
                "run_workload",
                "explain_workload",
                "profile_workload",
            ):
                arg = workload if method.endswith("_workload") else query
                result = getattr(executor, method)(arg)
                results = result if isinstance(result, list) else [result]
                assert all(r is not None and r.error is None for r in results)
                if method.startswith("run"):
                    assert all(r.row_count == 3 for r in results)
            started, cleaned = Event(), Event()

            async def controlled_operation():
                # Real driver call, then an interruptible wait with async cleanup.
                await executor._executor.run(query)
                started.set()
                try:
                    await asyncio.sleep(30)
                finally:
                    await asyncio.sleep(0.01)
                    cleaned.set()

            with monkeypatch.context() as interrupt:
                interrupt_sync_wait(interrupt, started, ready_timeout=15)
                with pytest.raises(KeyboardInterrupt):
                    executor._submit(controlled_operation)
            assert cleaned.is_set()
            assert executor.run(query).row_count == 3
        finally:
            executor.close()
            executor.close()
        assert not executor._worker.is_alive()
        assert executor._loop.is_closed()

    asyncio.run(notebook())
