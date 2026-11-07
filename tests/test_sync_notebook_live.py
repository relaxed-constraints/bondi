"""Opt-in read-only Docker smoke tests from an already-running caller loop."""

import asyncio
import os
import signal
from threading import Event, Thread

import pytest

from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

pytestmark = pytest.mark.live


@pytest.mark.parametrize("backend", ["mongo", "community", "enterprise"])
def test_notebook_live(backend, live_deployments):
    db = live_deployments("mongodb" if backend == "mongo" else backend)

    async def notebook():
        if backend == "mongo":
            executor = MongoExecutor.from_uri(db.uri, concurrency=2, timeout_seconds=10)
            query = MongoFindQuery(MongoCollectionRef("demo", "business"), {}, limit=3)
        else:
            executor = CouchbaseExecutor.from_uri(
                db.uri,
                username=db.username,
                password=db.password,
                concurrency=2,
                timeout_seconds=10,
            )
            query = CouchbaseQuery("SELECT RAW b FROM demo._default.business b LIMIT 3")
        try:
            assert executor._loop is not asyncio.get_running_loop()
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

            def interrupt():
                if started.wait(15):
                    os.kill(os.getpid(), signal.SIGINT)

            sender = Thread(target=interrupt)
            sender.start()
            try:
                # A notebook kernel delivers KeyboardInterrupt on its caller thread.
                # Override asyncio.run's SIGINT task-cancellation handler for this simulation.
                previous = signal.signal(signal.SIGINT, signal.default_int_handler)
                try:
                    with pytest.raises(KeyboardInterrupt):
                        executor._submit(controlled_operation)
                finally:
                    signal.signal(signal.SIGINT, previous)
            finally:
                sender.join()
            assert cleaned.is_set()
            assert executor.run(query).row_count == 3
        finally:
            executor.close()
            executor.close()
        assert not executor._worker.is_alive()
        assert executor._loop.is_closed()

    asyncio.run(notebook())
