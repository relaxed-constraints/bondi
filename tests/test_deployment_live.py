"""Opt in with BONDI_DEPLOYMENT_LIVE=1; creates/deletes an isolated Docker volume."""

import os
import socket

import pytest
from pymongo import MongoClient

from bondi.deployment import deploy_mongodb, get_deployment, list_deployments

pytestmark = pytest.mark.skipif(
    os.environ.get("BONDI_DEPLOYMENT_LIVE") != "1", reason="requires local Docker"
)


def test_mongo_lifecycle_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    try:
        db = deploy_mongodb("lifecycle-test", port=port)
        assert db.status() == "running"
        with MongoClient(db.uri, serverSelectionTimeoutMS=5000) as client:
            client.demo.records.insert_one({"_id": "retained"})
        db.stop()
        assert db.status() == "stopped"
        db.start()
        db.remove()
        assert db.status() == "removed"
        db = deploy_mongodb("lifecycle-test", port=port)
        with MongoClient(db.uri, serverSelectionTimeoutMS=5000) as client:
            assert client.demo.records.find_one({"_id": "retained"}) is not None
        assert db.logs()
    finally:
        if list_deployments():
            get_deployment("lifecycle-test").remove(delete_data=True)
    assert list_deployments() == []
