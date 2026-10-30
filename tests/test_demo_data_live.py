"""Opt-in end-to-end demo loads on isolated MongoDB and Couchbase deployments."""

import os
import socket
from contextlib import ExitStack

import pytest
from pymongo import MongoClient

from bondi._cli import main
from bondi.deployment import deploy_couchbase, deploy_mongodb
from bondi.deployment._couchbase import request

pytestmark = pytest.mark.skipif(
    os.environ.get("BONDI_DEPLOYMENT_LIVE") != "1", reason="requires local Docker"
)


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_load_repeat_cli_and_preserve_other_data(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket()) for _ in range(3)]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in sockets]
    db = None
    try:
        if backend == "mongodb":
            db = deploy_mongodb("demo-load-test", port=ports[0])
        else:
            db = deploy_couchbase(
                "demo-load-test", management_port=ports[0], query_port=ports[1], kv_port=ports[2]
            )
        assert db.load_demo_data().document_count == 8
        if backend == "mongodb":
            with MongoClient(db.uri) as client:
                client.demo.business.insert_one({"_id": "keep", "value": 42})
                client.demo.business.update_one({"_id": "demo-001"}, {"$set": {"name": "changed"}})
        else:
            response = request(
                db,
                "/query/service",
                {
                    "statement": "UPSERT INTO `demo`.`_default`.`business` (KEY, VALUE) "
                    'VALUES ("keep", {"value":42}), ("demo-001", {"name":"changed"})'
                },
                query=True,
            )
            assert response["status"] == "success", response
        args = ["load-demo-data", db.name]
        if backend == "couchbase":
            args += ["--create-primary-index"]
        assert main(args) == 0
        assert main(args) == 0  # Index creation is repeatable too.
        if backend == "mongodb":
            with MongoClient(db.uri) as client:
                assert client.demo.business.count_documents({}) == 9
                assert client.demo.business.find_one({"_id": "keep"})["value"] == 42
                assert client.demo.business.find_one({"_id": "demo-001"})["name"] == "Harbour Cafe"
            result = db.load_demo_data(database="research", collection="businesses")
            assert result.database == "research"
        else:
            response = request(
                db,
                "/query/service",
                {
                    "statement": "SELECT RAW b FROM `demo`.`_default`.`business` b",
                    "scan_consistency": "request_plus",
                },
                query=True,
            )
            assert response["status"] == "success", response
            assert len(response["results"]) == 9
            assert {"value": 42} in response["results"]
            assert any(d.get("name") == "Harbour Cafe" for d in response["results"])
            result = db.load_demo_data(scope="research", collection="businesses")
            assert result.scope == "research"
        db.stop()
        assert main(["load-demo-data", db.name]) == 1
    finally:
        if db is not None:
            db.remove(delete_data=True)
