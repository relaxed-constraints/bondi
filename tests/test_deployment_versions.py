"""Version selection and saved-image compatibility without Docker."""

import json
import subprocess
from unittest.mock import patch

import pytest

from bondi._cli import main
from bondi.deployment import deploy_couchbase, deploy_mongodb, get_deployment, list_deployments


@pytest.fixture
def docker(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with (
        patch("bondi.deployment._deployment._check_port") as port,
        patch("bondi.deployment._deployment.subprocess.run") as run,
        patch("bondi.deployment._couchbase.initialize"),
    ):
        run.return_value.stdout = ""
        yield port, run


@pytest.fixture(params=["mongodb", "community", "enterprise"])
def backend(request):
    if request.param == "mongodb":
        return deploy_mongodb, {}, "mongo:", "8.0.16", "8.0.17"
    return (
        deploy_couchbase,
        {"edition": request.param},
        f"couchbase:{request.param}-",
        "7.6.2",
        "7.6.12",
    )


def snapshot(db):
    return {path.name: path.read_bytes() for path in db._path.iterdir()}


def test_defaults_and_explicit_selection(docker, backend):
    deploy, kwargs, prefix, default, version = backend
    assert deploy("default", **kwargs).image == prefix + default
    db = deploy("selected", version=version, **kwargs)
    assert db.image == prefix + version
    config = json.loads((db._path / "deployment.json").read_text())
    compose = json.loads((db._path / "compose.json").read_text())
    assert config["image"] == compose["services"][db.backend]["image"] == db.image
    before = snapshot(db)
    assert deploy("selected", **kwargs) == db
    assert deploy("selected", version=version, **kwargs) == db
    db.stop()
    get_deployment("selected").start()
    db.remove(keep_data=True)  # Retain data; recreation must also preserve the version.
    get_deployment("selected").start()
    assert snapshot(db) == before


def test_explicit_default_conflict_is_read_only(docker, backend):
    deploy, kwargs, _, default, version = backend
    db = deploy("selected", version=version, **kwargs)
    before = snapshot(db)
    port, run = docker
    port.reset_mock()
    run.reset_mock()
    with pytest.raises(ValueError, match="version"):
        deploy("selected", version=default, **kwargs)
    port.assert_not_called()
    run.assert_not_called()
    assert snapshot(db) == before


@pytest.mark.parametrize("custom", [False, True])
def test_legacy_images_are_preserved(docker, backend, custom):
    deploy, kwargs, prefix, default, version = backend
    db = deploy("legacy", **kwargs)
    # Version-1 metadata only stores image, including manual maintenance upgrades.
    image = "private.example/database:maintenance" if custom else prefix + version
    metadata = db._path / "deployment.json"
    config = json.loads(metadata.read_text())
    assert "version" not in config
    config["image"] = image
    metadata.write_text(json.dumps(config))
    compose_path = db._path / "compose.json"
    compose = json.loads(compose_path.read_text())
    compose["services"][db.backend]["image"] = image
    compose_path.write_text(json.dumps(compose))
    before = snapshot(db)
    assert deploy("legacy", **kwargs).image == image
    get_deployment("legacy").stop()
    get_deployment("legacy").start()
    if not custom:
        assert deploy("legacy", version=version, **kwargs).image == image
    docker[1].reset_mock()
    with pytest.raises(ValueError, match="version"):
        deploy("legacy", version=default, **kwargs)
    docker[1].assert_not_called()
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "version",
    [
        "",
        "latest",
        "8",
        "8.0",
        "v8.0.16",
        "8.0.16-alpine",
        "8.0.16\n",
        " 8.0.16",
        "mongo:8.0.16",
        "8.0.16/other",
        True,
        8,
        8.0,
        [],
        {},
    ],
)
def test_invalid_versions_have_no_side_effects(docker, backend, tmp_path, version):
    deploy, kwargs, *_ = backend
    with pytest.raises(ValueError, match="version"):
        deploy(version=version, **kwargs)
    for mock in docker:
        mock.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_unavailable_image_error_and_cleanup(docker, backend):
    deploy, kwargs, prefix, *_ = backend
    _, run = docker
    run.side_effect = [
        subprocess.CalledProcessError(1, "docker", stderr="manifest unknown"),
        subprocess.CompletedProcess([], 0, stdout=""),
    ]
    with pytest.raises(RuntimeError) as error:
        deploy(version="999.0.0", **kwargs)
    assert prefix + "999.0.0" in str(error.value)
    assert "manifest unknown" in str(error.value)
    assert "tag exists for your platform" in str(error.value)
    assert list_deployments() == []


def test_cli_version_selection_and_conflict(docker, backend, capsys):
    deploy, kwargs, prefix, default, version = backend
    name = "mongodb" if deploy is deploy_mongodb else "couchbase"
    args = ["deployment", "create", name]
    if kwargs:
        args += ["--edition", kwargs["edition"]]
    assert main([*args, "--version", version]) == 0
    assert get_deployment(name).image == prefix + version
    assert main(args) == 0
    docker[1].reset_mock()
    assert main([*args, "--version", default]) == 1
    assert "version" in capsys.readouterr().err
    docker[1].assert_not_called()
