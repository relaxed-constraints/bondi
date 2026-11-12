"""Opt-in checks against isolated, fixture-owned MongoDB/Couchbase deployments."""

import pytest

from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery
from bondi.load import Sequential, UniformRandom
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

pytestmark = pytest.mark.live


@pytest.mark.parametrize("backend", ["mongodb", "community"])
def test_generate_load_live(backend, live_deployments):
    deployment = live_deployments(backend)
    if backend == "mongodb":
        executor = MongoExecutor.from_uri(
            deployment.uri,
            concurrency=3,
            timeout_seconds=5,
            health_check_timeout_seconds=2,
        )
        query = MongoFindQuery(MongoCollectionRef("demo", "business"), {})
    else:
        executor = CouchbaseExecutor.from_uri(
            deployment.uri,
            username=deployment.username,
            password=deployment.password,
            concurrency=3,
            timeout_seconds=5,
            health_check_timeout_seconds=2,
        )
        query = CouchbaseQuery("SELECT RAW b FROM `demo`.`_default`.`business` AS b")
    workload = Workload([WorkloadEntry(query)])
    delivered = []
    with executor:
        results = executor.generate_load(
            workload,
            selection=UniformRandom(seed=42),
            warmup_seconds=0.1,
            measurement_seconds=0.3,
            drain_timeout_seconds=8,
            collect_results=True,
            on_result=delivered.append,
        )
        assert results and results == delivered
        assert {r.client_id for r in results} == {0, 1, 2}
        assert all(r.result is not None and r.result.status == "success" for r in results)
        assert all(r.query_started and r.result.row_count == 8 for r in results)
        assert all(len(r.result.documents) == 8 for r in results)
        assert all(r.admitted_seconds < 0.4 and r.duration >= 0 for r in results)
        streamed = []
        assert (
            executor.generate_load(
                workload,
                selection=Sequential(),
                measurement_seconds=0.1,
                drain_timeout_seconds=8,
                return_load_results=False,
                on_result=streamed.append,
            )
            == []
        )
        assert streamed and all(r.result.documents is None for r in streamed)
