"""Opt-in isolated Community/Enterprise lifecycle and SDK connectivity tests."""

import os
import socket
import subprocess
import sys
from contextlib import ExitStack

import pytest

from bondi.deployment import deploy_couchbase, get_deployment, list_deployments

pytestmark = pytest.mark.skipif(
    os.environ.get("BONDI_DEPLOYMENT_LIVE") != "1", reason="requires local Docker"
)


@pytest.mark.parametrize("edition", ["community", "enterprise"])
def test_couchbase_lifecycle(tmp_path, monkeypatch, edition):
    from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery

    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket()) for _ in range(3)]
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        ports = [sock.getsockname()[1] for sock in sockets]
    try:
        db = deploy_couchbase(
            "cb-test",
            management_port=ports[0],
            query_port=ports[1],
            kv_port=ports[2],
            edition=edition,
        )
        assert db.status() == "running"
        command = subprocess.run(
            [
                sys.executable,
                "-m",
                "bondi",
                "deploy",
                "couchbase",
                "--name",
                "cb-test",
                "--management-port",
                str(ports[0]),
                "--query-port",
                str(ports[1]),
                "--kv-port",
                str(ports[2]),
                "--edition",
                edition,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert command.returncode == 0, command.stderr
        assert db.console_url in command.stdout
        assert "Password: bondi-local" in command.stdout
        with CouchbaseExecutor.from_uri(
            db.uri, username=db.username, password=db.password, timeout_seconds=30
        ) as executor:
            result = executor.run(
                CouchbaseQuery('UPSERT INTO `demo` (KEY, VALUE) VALUES ("keep", {"value":42})')
            )
            assert result.error is None
        db.stop()
        assert db.status() == "stopped"
        db.start(timeout=180)
        db.remove()
        assert db.status() == "removed"
        db.start(timeout=180)
        with CouchbaseExecutor.from_uri(
            db.uri, username=db.username, password=db.password, timeout_seconds=30
        ) as executor:
            result = executor.run(
                CouchbaseQuery('SELECT RAW d.`value` FROM `demo` d USE KEYS "keep"'),
                collect_results=True,
            )
            assert result.error is None
            assert result.documents == [42]
    finally:
        if list_deployments():
            get_deployment("cb-test").remove(delete_data=True)
    assert list_deployments() == []
