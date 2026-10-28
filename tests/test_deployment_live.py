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


def test_failed_new_setup_rolls_back_real_resources(tmp_path, monkeypatch):
    """Inject a failure after Docker starts to verify actual rollback and port retry."""
    import subprocess
    from unittest.mock import patch

    from bondi.deployment import Deployment

    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    original_start = Deployment.start
    projects = []

    def fail_after_start(self, **kwargs):
        projects.append(self._project)
        original_start(self, **kwargs)
        raise RuntimeError("injected startup failure")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        first_port = sock.getsockname()[1]
    try:
        with patch.object(Deployment, "start", fail_after_start):
            with pytest.raises(RuntimeError, match="new deployment and its data were removed"):
                deploy_mongodb("rollback-test", port=first_port)
        assert list_deployments() == []
        for resource, command in [
            ("container", ["ps", "-aq"]),
            ("volume", ["volume", "ls", "-q"]),
            ("network", ["network", "ls", "-q"]),
        ]:
            result = subprocess.run(
                ["docker", *command, "--filter", f"label=com.docker.compose.project={projects[0]}"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert not result.stdout.strip(), resource
        # Keep the original port occupied while retrying the same name on another.
        with socket.socket() as occupied, socket.socket() as free:
            occupied.bind(("127.0.0.1", first_port))
            occupied.listen()
            free.bind(("127.0.0.1", 0))
            retry_port = free.getsockname()[1]
            free.close()
            db = deploy_mongodb("rollback-test", port=retry_port)
            assert db.status() == "running"
    finally:
        for db in list_deployments():
            db.remove(delete_data=True)
