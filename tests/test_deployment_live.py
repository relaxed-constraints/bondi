"""Opt in with BONDI_LIVE=1; creates/deletes an isolated Docker volume."""

import socket

import pytest
from pymongo import MongoClient

from bondi.deployment import deploy_mongodb, get_deployment, list_deployments

pytestmark = pytest.mark.live


def test_mongo_lifecycle_and_persistence(tmp_path, monkeypatch, live_ports):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    port = live_ports.claim("mongodb")[0]
    try:
        db = deploy_mongodb("lifecycle-test", port=port)
        assert db.status() == "running"
        with MongoClient(db.uri, serverSelectionTimeoutMS=5000) as client:
            client.demo.records.insert_one({"_id": "retained"})
        db.stop()
        assert db.status() == "stopped"
        db.start()
        db.remove(keep_data=True)
        assert db.status() == "removed"
        db = deploy_mongodb("lifecycle-test", port=port)
        with MongoClient(db.uri, serverSelectionTimeoutMS=5000) as client:
            assert client.demo.records.find_one({"_id": "retained"}) is not None
        assert db.logs()
        db.remove()
        assert list_deployments() == []
        assert not db._data_volume_exists()
        db = deploy_mongodb("lifecycle-test", port=port)
        with MongoClient(db.uri, serverSelectionTimeoutMS=5000) as client:
            assert client.demo.records.count_documents({}) == 0
        result = db.load_demo_data()
        assert result.document_count == 8
    finally:
        if list_deployments():
            get_deployment("lifecycle-test").remove()
    assert list_deployments() == []


def test_cli_lifecycle(tmp_path, monkeypatch, live_ports):
    """Exercise actual command parsing and exit codes against an isolated deployment."""
    import subprocess
    import sys

    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    port = live_ports.claim("mongodb")[0]

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
        assert cli("remove", "cli-test", "--keep-data", "-y").returncode == 0
        assert "removed" in cli("status", "cli-test").stdout
        assert cli("remove", "cli-test", "-y").returncode == 0
        assert cli("status", "cli-test").returncode == 1
        assert "No saved deployments" in cli("list").stdout
    finally:
        if list_deployments():
            get_deployment("cli-test").remove()


def test_failed_new_setup_rolls_back_real_resources(tmp_path, monkeypatch, live_ports):
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

    first_port = live_ports.claim("mongodb")[0]
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
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", first_port))
            occupied.listen()
            retry_port = live_ports.claim("mongodb")[0]
            db = deploy_mongodb("rollback-test", port=retry_port)
            assert db.status() == "running"
    finally:
        for db in list_deployments():
            db.remove()


def test_mongo_memory_limits(tmp_path, monkeypatch, live_ports):
    """Observe both limits in a disposable deployment, including after restart."""
    import json
    import subprocess

    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    name = "memory-test"
    try:
        db = deploy_mongodb(
            name,
            port=live_ports.claim("mongodb")[0],
            memory_limit_mb=1024,
            wiredtiger_cache_size_gb=0.25,
        )
        for restart in (False, True):
            if restart:
                db.stop()
                db.start()
            container = db._run("ps", "-q", "mongodb").strip()
            inspected = subprocess.run(
                ["docker", "inspect", container], capture_output=True, text=True, check=True
            )
            assert json.loads(inspected.stdout)[0]["HostConfig"]["Memory"] == 1024 * 1024**2
            with MongoClient(db.uri, serverSelectionTimeoutMS=5000) as client:
                status = client.admin.command("serverStatus")
                assert status["wiredTiger"]["cache"]["maximum bytes configured"] == 256 * 1024**2
    finally:
        for db in list_deployments():
            db.remove()
