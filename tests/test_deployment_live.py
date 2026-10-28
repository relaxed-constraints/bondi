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


def test_cli_lifecycle(tmp_path, monkeypatch):
    """Exercise actual command parsing and exit codes against an isolated deployment."""
    import subprocess
    import sys

    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    def cli(*args):
        return subprocess.run(
            [sys.executable, "-m", "bondi", *args], capture_output=True, text=True, timeout=150
        )

    try:
        result = cli("deploy", "mongodb", "--name", "cli-test", "--port", str(port))
        assert result.returncode == 0, result.stderr
        assert f":{port}/" in result.stdout
        assert "cli-test: running" in cli("list").stdout
        assert cli("logs", "cli-test", "--tail", "2").returncode == 0
        assert cli("stop", "cli-test").returncode == 0
        assert "stopped" in cli("status", "cli-test").stdout
        assert cli("start", "cli-test").returncode == 0
        assert cli("remove", "cli-test").returncode == 0
        assert "removed" in cli("status", "cli-test").stdout
        assert cli("remove", "cli-test", "--delete-data").returncode == 0
        assert cli("status", "cli-test").returncode == 1
        assert "No saved deployments" in cli("list").stdout
    finally:
        if list_deployments():
            get_deployment("cli-test").remove(delete_data=True)
