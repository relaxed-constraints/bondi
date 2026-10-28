"""Deployment contracts without a Docker daemon."""

import json
import subprocess
from unittest.mock import patch

import pytest

from bondi.deployment import deploy_mongodb, get_deployment, list_deployments


@pytest.fixture
def compose(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with patch("bondi.deployment._deployment.subprocess.run") as run:
        run.return_value.stdout = ""
        yield run


def test_create_reuse_and_conflict(compose):
    db = deploy_mongodb("demo", port=27019)
    assert db.uri == "mongodb://127.0.0.1:27019/"
    assert get_deployment("demo") == db
    assert list_deployments() == [db]
    config = json.loads((db._path / "compose.json").read_text())
    assert config["services"]["mongodb"]["ports"] == ["127.0.0.1:27019:27017"]
    assert "--wait" in compose.call_args.args[0]
    assert deploy_mongodb("demo", port=27019) == db
    before = compose.call_count
    with pytest.raises(ValueError, match="already uses"):
        deploy_mongodb("demo", port=27020)
    assert compose.call_count == before


@pytest.mark.parametrize("name", ["../oops", "", "UPPER", "a/b", "a" * 49])
def test_invalid_name(compose, name):
    with pytest.raises(ValueError):
        deploy_mongodb(name)
    compose.assert_not_called()


@pytest.mark.parametrize("port", [True, 0, 65536, "27017"])
def test_invalid_port(compose, port):
    with pytest.raises(ValueError):
        deploy_mongodb(port=port)
    compose.assert_not_called()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_timeout(compose, timeout):
    with pytest.raises(ValueError):
        deploy_mongodb(timeout=timeout)
    compose.assert_not_called()


def test_remove_retains_data_and_configuration(compose):
    db = deploy_mongodb()
    db.stop()
    db.remove()
    assert compose.call_args.args[0][-1] == "down"
    assert get_deployment("mongodb") == db
    db.start()
    db.remove(delete_data=True)
    assert compose.call_args.args[0][-2:] == ["down", "--volumes"]
    assert list_deployments() == []
    with pytest.raises(RuntimeError, match="deleted"):
        db.start()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("", "removed"),
        ("[]", "removed"),
        ('{"State":"exited"}', "stopped"),
        ('[{"State":"running","Health":"healthy"}]', "running"),
        ('{"State":"running","Health":"starting"}', "starting"),
        ('{"State":"running","Health":"unhealthy"}', "unhealthy"),
    ],
)
def test_status(compose, payload, expected):
    db = deploy_mongodb()
    compose.return_value.stdout = payload
    assert db.status() == expected


@pytest.mark.parametrize(
    "error,message",
    [
        (FileNotFoundError(), "Docker was not found"),
        (subprocess.TimeoutExpired("docker", 1), "timed out"),
        (subprocess.CalledProcessError(1, "docker", stderr="port occupied"), "port occupied"),
    ],
)
def test_failure_retains_configuration(compose, error, message):
    compose.side_effect = error
    with pytest.raises(RuntimeError, match=message):
        deploy_mongodb()
    assert get_deployment("mongodb").port == 27017
    compose.side_effect = None
    deploy_mongodb()


def test_failed_delete_keeps_configuration(compose):
    db = deploy_mongodb()
    compose.side_effect = subprocess.CalledProcessError(1, "docker", stderr="unavailable")
    with pytest.raises(RuntimeError):
        db.remove(delete_data=True)
    assert get_deployment("mongodb") == db


def test_distinct_projects_and_logs(compose):
    first = deploy_mongodb("first")
    second = deploy_mongodb("second", port=27019)
    assert first._project != second._project
    compose.return_value.stdout = "ready"
    assert first.logs(tail=10) == "ready"
    assert compose.call_args.args[0][-5:] == ["logs", "--no-color", "--tail", "10", "mongodb"]
