"""Opt-in real-server checks using only a uniquely named disposable database.

Set DBRTOOLKIT_TEST_MONGODB_URI to run. The caller owns the MongoDB server.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from dbrtoolkit.mongodb import (
    AsyncMongoDBExecutor,
    MongoAggregateQuery,
    MongoCollectionRef,
    MongoFindQuery,
    summarize_explain,
)
from dbrtoolkit.workload import Workload, WorkloadEntry


def test_executor_against_mongodb():
    uri = os.environ.get("DBRTOOLKIT_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("Set DBRTOOLKIT_TEST_MONGODB_URI for live checks")

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=3000)
        database = f"dbrtoolkit_test_{uuid4().hex}"
        try:
            collection = client[database]["items"]
            await collection.insert_many([{"x": i} for i in range(25)])
            target = MongoCollectionRef(database, "items")
            executor = AsyncMongoDBExecutor(
                client, concurrency=2, timeout_seconds=10, continue_on_error=True
            )
            find = MongoFindQuery(
                target, {"x": {"$gte": 5}}, {"x": 1, "_id": 0}, (("x", -1),), 2, 5
            )
            result = await executor.run(find, collect_results=True, query_kwargs={"batch_size": 2})
            assert result.documents == [{"x": i} for i in range(22, 17, -1)]
            assert result.row_count == 5
            aggregate = MongoAggregateQuery(target, [{"$match": {"x": {"$gte": 5}}}])
            result = await executor.run(aggregate, query_kwargs={"batchSize": 2})
            assert result.row_count == 20 and result.documents is None
            work = Workload([WorkloadEntry(find), WorkloadEntry(aggregate)])
            results = await executor.run_workload(work)
            assert [r.row_count for r in results] == [5, 20]
            explains = await executor.profile_workload(
                work, verbosity="executionStats", command_kwargs={"maxTimeMS": 5000}
            )
            assert all(r.status == "success" and r.raw["ok"] == 1 for r in explains)
            assert [summarize_explain(r.raw).rows_returned for r in explains] == [5, 20]
            plans = await executor.explain_workload(work)
            assert all("executionStats" not in r.raw for r in plans)
            assert all(summarize_explain(r.raw).rows_returned is None for r in plans)
            bad = MongoFindQuery(target, {"$invalidOperator": 1})
            results = await executor.run_workload(
                Workload([WorkloadEntry(bad), WorkloadEntry(find)])
            )
            assert results[0].status == "error"
            assert results[1].row_count == 5
            await executor.close()
            await client.admin.command("ping")  # Borrowed client remains usable.
        finally:
            await client.drop_database(database)
            await client.close()

    asyncio.run(scenario())
