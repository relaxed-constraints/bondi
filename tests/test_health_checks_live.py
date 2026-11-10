"""Bounded probes against test-owned deployments; never stop shared research databases."""

import asyncio
import time

import pytest
from pymongo import AsyncMongoClient

from bondi.deployment import deploy_couchbase, deploy_mongodb, list_deployments
from bondi.execution import DatabaseUnavailableError
from bondi.mongodb import AsyncMongoExecutor, MongoExecutor

pytestmark = pytest.mark.live


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_healthy_and_stopped_probe(tmp_path, monkeypatch, live_ports, backend):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    try:
        if backend == "mongodb":
            db = deploy_mongodb("health-mongo", port=live_ports.claim("mongodb")[0])
            executor = MongoExecutor.from_uri(
                db.uri,
                timeout_seconds=600,
                health_check_timeout_seconds=0.2,
                client_kwargs={"serverSelectionTimeoutMS": 600000, "connectTimeoutMS": 600000},
            )
        else:
            pytest.importorskip("couchbase")
            from bondi.couchbase import CouchbaseExecutor

            management, query, kv = live_ports.claim("couchbase")
            db = deploy_couchbase(
                "health-couchbase", management_port=management, query_port=query, kv_port=kv
            )
            executor = CouchbaseExecutor.from_uri(
                db.uri,
                username=db.username,
                password=db.password,
                timeout_seconds=600,
                health_check_timeout_seconds=0.2,
            )
        with executor:
            assert executor.ping(timeout_seconds=2) is None
            db.stop()
            try:
                start = time.monotonic()
                with pytest.raises(DatabaseUnavailableError):
                    executor.ping(timeout_seconds=0.2)
                assert time.monotonic() - start < 2
            finally:
                # Driver close may send endSessions using the long client settings.
                # Restore only this test-owned server before closing the owned client.
                db.start()

        if backend == "mongodb":
            db.stop()

            async def borrowed():
                client = AsyncMongoClient(
                    db.uri,
                    serverSelectionTimeoutMS=600000,
                    timeoutMS=600000,
                    connectTimeoutMS=600000,
                )
                try:
                    executor = AsyncMongoExecutor(client, timeout_seconds=600)
                    start = time.monotonic()
                    with pytest.raises(DatabaseUnavailableError):
                        await executor.ping(timeout_seconds=0.2)
                    assert time.monotonic() - start < 2
                    await executor.close()
                    assert not client._closed
                finally:
                    await client.close()

            asyncio.run(borrowed())
    finally:
        for db in list_deployments():
            db.remove(delete_data=True)
