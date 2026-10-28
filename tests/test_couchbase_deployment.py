"""Couchbase configuration, initialization and CLI contracts without Docker."""

import json
import os
import time
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from bondi._cli import main
from bondi.deployment import _couchbase, deploy_couchbase, deploy_mongodb, get_deployment


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with (
        patch("bondi.deployment._deployment._check_port") as port,
        patch("bondi.deployment._deployment.subprocess.run") as run,
        patch.object(_couchbase, "initialize") as init,
    ):
        run.return_value.stdout = ""
        yield port, run, init


def test_config_assets_and_private_metadata(setup):
    port, run, init = setup
    db = deploy_couchbase(
        "cb",
        management_port=9091,
        query_port=9093,
        kv_port=11211,
        password="private-test-value",
        bucket="research",
    )
    assert db.backend == "couchbase"
    assert db.uri == "couchbase://127.0.0.1:11211?network=external"
    assert db.console_url == "http://127.0.0.1:9091/"
    assert "private-test-value" not in repr(db)
    assert [c.args[0] for c in port.call_args_list] == [9091, 9093, 11211]
    compose = json.loads((db._path / "compose.json").read_text())
    assert compose["services"]["couchbase"]["ports"] == [
        "127.0.0.1:9091:8091",
        "127.0.0.1:9093:8093",
        "127.0.0.1:11211:11210",
    ]
    assert "private-test-value" not in json.dumps(compose)
    assert init.call_args.args[0] == db
    assert get_deployment("cb") == db
    if os.name == "posix":
        assert (db._path / "deployment.json").stat().st_mode & 0o777 == 0o600
        assert db._path.stat().st_mode & 0o777 == 0o700


def test_reuse_and_conflicts(setup):
    db = deploy_couchbase(password="secret-one")
    assert deploy_couchbase(password="secret-one") == db
    for kwargs in [{"password": "secret-two"}, {"edition": "enterprise"}, {"bucket": "other"}]:
        with pytest.raises(ValueError) as error:
            deploy_couchbase(**kwargs)
        assert "secret-one" not in str(error.value)
        assert "secret-two" not in str(error.value)
    with pytest.raises(ValueError, match="backend"):
        deploy_mongodb("couchbase")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"edition": "invalid"},
        {"management_port": 0},
        {"query_port": True},
        {"kv_port": 8091},
        {"password": "short"},
        {"username": "bad:name"},
        {"bucket": "bad/name"},
    ],
)
def test_invalid_before_docker(setup, kwargs):
    _, run, _ = setup
    with pytest.raises(ValueError):
        deploy_couchbase(**kwargs)
    run.assert_not_called()


def test_initialize_failure_rolls_back(setup):
    _, run, init = setup
    init.side_effect = ValueError("Couchbase HTTP 400")
    with pytest.raises(RuntimeError, match="removed"):
        deploy_couchbase()
    assert run.call_args.args[0][-2:] == ["down", "--volumes"]
    with pytest.raises(FileNotFoundError):
        get_deployment("couchbase")


@pytest.mark.parametrize("edition,storage", [("community", "forestdb"), ("enterprise", "plasma")])
@pytest.mark.parametrize("existing", [False, True])
def test_initialization_and_restarts(setup, edition, storage, existing):
    db = deploy_couchbase(edition=edition)
    responses = [{"pools": [{}] if existing else []}]
    if not existing:
        responses.append(None)  # clusterInit
    responses.extend([{}, None, [{"name": "demo"}] if existing else []])
    if not existing:
        responses.append(None)  # bucket creation
    responses.append(
        {
            "nodesExt": [
                {
                    "services": {"kv": 11210, "n1ql": 8093, "mgmt": 8091},
                    "alternateAddresses": {
                        "external": {
                            "hostname": "127.0.0.1",
                            "ports": {"mgmt": 8091, "n1ql": 8093, "kv": 11210},
                        }
                    },
                }
            ]
        }
    )
    responses.extend([{"nodes": [{"status": "healthy"}]}, {"status": "success", "results": [1]}])
    with patch.object(_couchbase, "request", side_effect=responses) as req:
        ORIGINAL_INITIALIZE(db, deadline=time.monotonic() + 10)
    calls = req.call_args_list
    init = [c for c in calls if c.args[1] == "/clusterInit"]
    assert bool(init) is not existing
    if init:
        assert init[0].args[2]["indexerStorageMode"] == storage
    alternate = next(c for c in calls if "setupAlternateAddresses" in c.args[1])
    assert alternate.args[2] == {"hostname": "127.0.0.1", "mgmt": 8091, "n1ql": 8093, "kv": 11210}


ORIGINAL_INITIALIZE = _couchbase.initialize


def test_http_error_hides_body_and_credentials(setup):
    db = deploy_couchbase(password="hidden-password")
    error = HTTPError("http://localhost", 401, "hidden-password", {}, None)
    with patch.object(_couchbase, "urlopen", side_effect=error):
        with pytest.raises(ValueError, match="HTTP 401") as failure:
            _couchbase.request(db, "/pools/default")
    assert "hidden-password" not in str(failure.value)


def test_cli_couchbase_defaults_and_env(capsys, monkeypatch):
    db = MagicMock(name="cb")
    db.name = "couchbase"
    db.uri = "couchbase://127.0.0.1:11210?network=external"
    db.console_url = "http://127.0.0.1:8091/"
    db.username = "Administrator"
    monkeypatch.setenv("TEST_CB_PASSWORD", "hidden-password")
    with patch("bondi._cli.deploy_couchbase", return_value=db) as deploy:
        assert main(["deploy", "couchbase"]) == 0
        assert deploy.call_args.kwargs["edition"] == "community"
        assert deploy.call_args.kwargs["password"] == "bondi-local"
        assert (
            main(
                [
                    "deploy",
                    "couchbase",
                    "--password-env",
                    "TEST_CB_PASSWORD",
                    "--edition",
                    "enterprise",
                    "--management-port",
                    "9091",
                ]
            )
            == 0
        )
        assert deploy.call_args.kwargs["password"] == "hidden-password"
        assert deploy.call_args.kwargs["management_port"] == 9091
    assert "hidden-password" not in capsys.readouterr().out


def test_status_requires_query_readiness(setup):
    _, run, _ = setup
    db = deploy_couchbase()
    run.return_value.stdout = '{"State":"running","Health":"healthy"}'
    with patch.object(_couchbase, "ready", side_effect=RuntimeError("not ready")):
        assert db.status() == "starting"
    with patch.object(_couchbase, "ready"):
        assert db.status() == "running"


def test_initialization_deadline(setup):
    db = deploy_couchbase()
    with pytest.raises(RuntimeError, match="timed out"):
        ORIGINAL_INITIALIZE(db, deadline=time.monotonic() - 1)


def test_missing_password_env_does_not_deploy(monkeypatch, capsys):
    monkeypatch.delenv("MISSING_CB_PASSWORD", raising=False)
    with patch("bondi._cli.deploy_couchbase") as deploy:
        assert main(["deploy", "couchbase", "--password-env", "MISSING_CB_PASSWORD"]) == 1
        deploy.assert_not_called()
    assert "unset" in capsys.readouterr().err
