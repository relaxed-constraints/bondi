"""Deployment contracts without a Docker daemon."""

import json
import socket
import subprocess
from unittest.mock import patch

import pytest

from bondi.deployment import deploy_mongodb, get_deployment, list_deployments


@pytest.fixture
def compose(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with (
        patch("bondi.deployment._deployment._check_port"),
        patch("bondi.deployment._deployment.subprocess.run") as run,
    ):
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


@pytest.mark.parametrize(
    "error",
    [
        subprocess.CalledProcessError(1, "docker", stderr="port allocated after preflight"),
        subprocess.TimeoutExpired("docker", 1),
    ],
)
def test_failed_new_start_is_cleaned_and_can_change_port(compose, error):
    compose.side_effect = [error, subprocess.CompletedProcess([], 0, stdout="")]
    with pytest.raises(RuntimeError, match="new deployment and its data were removed"):
        deploy_mongodb("new", port=27019)
    assert list_deployments() == []
    assert compose.call_args.args[0][-2:] == ["down", "--volumes"]
    compose.side_effect = None
    assert deploy_mongodb("new", port=27020).port == 27020


def test_existing_start_failure_never_deletes_data(compose):
    db = deploy_mongodb()
    compose.reset_mock()
    compose.side_effect = subprocess.TimeoutExpired("docker", 1)
    with pytest.raises(RuntimeError, match="Existing deployment.*retained"):
        deploy_mongodb()
    assert compose.call_count == 1
    assert get_deployment("mongodb") == db


def test_failed_cleanup_has_recovery_instructions(compose):
    compose.side_effect = subprocess.CalledProcessError(1, "docker", stderr="daemon unavailable")
    with pytest.raises(RuntimeError, match="bondi remove demo --delete-data"):
        deploy_mongodb("demo")
    assert get_deployment("demo").port == 27017


def test_interrupted_new_start_is_cleaned(compose):
    compose.side_effect = [KeyboardInterrupt(), subprocess.CompletedProcess([], 0, stdout="")]
    with pytest.raises(KeyboardInterrupt):
        deploy_mongodb()
    assert list_deployments() == []


def test_busy_port_leaves_no_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with patch("bondi.deployment._deployment.subprocess.run") as run:
            with pytest.raises(RuntimeError, match="No deployment was created"):
                deploy_mongodb("busy", port=occupied.getsockname()[1])
            run.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_configuration_write_failure_is_cleaned(compose, tmp_path):
    from pathlib import Path

    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            deploy_mongodb()
    compose.assert_not_called()
    assert list(tmp_path.iterdir()) == []
