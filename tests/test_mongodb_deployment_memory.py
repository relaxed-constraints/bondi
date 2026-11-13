"""MongoDB memory configuration, reuse and immutable existing assets."""

import json
import warnings
from unittest.mock import patch

import pytest

from bondi._cli import main
from bondi.deployment import deploy_mongodb, get_deployment


@pytest.fixture
def docker(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    with (
        patch("bondi.deployment._deployment._check_port"),
        patch("bondi.deployment._deployment.subprocess.run") as run,
    ):
        run.return_value.stdout = ""
        yield run


@pytest.mark.parametrize("memory,cache", [(None, None), (1024, None), (None, 0.25), (24576, 10)])
def test_render_roundtrip_and_reuse(docker, memory, cache):
    db = deploy_mongodb(memory_limit_mb=memory, wiredtiger_cache_size_gb=cache)
    assert get_deployment(db.name) == db
    assert db.memory_limit_mb == memory
    assert db.wiredtiger_cache_size_gb == cache
    service = json.loads((db._path / "compose.json").read_text())["services"]["mongodb"]
    assert service["ports"] == ["127.0.0.1:27017:27017"]
    assert service.get("mem_limit") == (None if memory is None else f"{memory}m")
    assert service.get("command") == (
        None
        if cache is None
        else ["mongod", "--bind_ip_all", "--wiredTigerCacheSizeGB", str(cache)]
    )
    before = [(db._path / name).read_bytes() for name in ("deployment.json", "compose.json")]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert deploy_mongodb() == db
        assert deploy_mongodb(memory_limit_mb=memory, wiredtiger_cache_size_gb=cache) == db
    assert not caught
    db.stop()
    db.start()
    assert before == [
        (db._path / name).read_bytes() for name in ("deployment.json", "compose.json")
    ]


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "1024", float("inf")])
def test_invalid_memory(docker, tmp_path, value):
    with pytest.raises(ValueError, match="memory_limit_mb"):
        deploy_mongodb(memory_limit_mb=value)
    docker.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "value", [True, False, 0, 0.249, 10001, "1", float("nan"), float("inf"), -float("inf"), 10**400]
)
def test_invalid_cache(docker, tmp_path, value):
    with pytest.raises(ValueError, match="wiredtiger_cache_size_gb"):
        deploy_mongodb(wiredtiger_cache_size_gb=value)
    docker.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("cache", [0.25, 10000])
def test_cache_bounds(docker, cache):
    assert deploy_mongodb(wiredtiger_cache_size_gb=cache).wiredtiger_cache_size_gb == cache


@pytest.mark.parametrize("cache", [1, 2])
def test_incompatible_new_limits(docker, tmp_path, cache):
    with pytest.raises(ValueError, match="smaller"):
        deploy_mongodb(memory_limit_mb=1024, wiredtiger_cache_size_gb=cache)
    docker.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_differing_requests_warn_and_keep_existing_assets(docker):
    db = deploy_mongodb(memory_limit_mb=1024, wiredtiger_cache_size_gb=0.25)
    path = db._path / "compose.json"
    assets = json.loads(path.read_text())
    assets["services"]["mongodb"]["labels"] = {"manual": "preserve"}
    path.write_text(json.dumps(assets))
    before = [(db._path / name).read_bytes() for name in ("deployment.json", "compose.json")]
    calls = docker.call_count
    # Even incompatible requested pairs are ignored: existing settings are authoritative.
    with pytest.warns(UserWarning) as caught:
        assert deploy_mongodb(memory_limit_mb=512, wiredtiger_cache_size_gb=1) == db
    assert len(caught) == 2
    assert "requested 512 MiB, existing 1024 MiB" in str(caught[0].message)
    assert "requested 1 GiB, existing 0.25 GiB" in str(caught[1].message)
    assert docker.call_count == calls + 1
    assert before == [
        (db._path / name).read_bytes() for name in ("deployment.json", "compose.json")
    ]


def test_legacy_manual_limits_are_not_adopted(docker):
    db = deploy_mongodb()
    metadata = db._path / "deployment.json"
    config = json.loads(metadata.read_text())
    del config["memory_limit_mb"]
    del config["wiredtiger_cache_size_gb"]
    metadata.write_text(json.dumps(config))
    compose = db._path / "compose.json"
    assets = json.loads(compose.read_text())
    assets["services"]["mongodb"]["mem_limit"] = "2048m"
    compose.write_text(json.dumps(assets))
    before = metadata.read_bytes(), compose.read_bytes()
    assert deploy_mongodb().memory_limit_mb is None
    with pytest.warns(UserWarning, match="existing not explicitly saved"):
        assert deploy_mongodb(memory_limit_mb=2048).memory_limit_mb is None
    assert before == (metadata.read_bytes(), compose.read_bytes())


def test_other_conflicts_still_fail(docker):
    deploy_mongodb(memory_limit_mb=1024)
    calls = docker.call_count
    with pytest.raises(ValueError, match="port"):
        deploy_mongodb(port=27019, memory_limit_mb=2048)
    assert docker.call_count == calls


def test_cli_options_status_and_warning(docker, capsys):
    assert (
        main(
            [
                "deployment",
                "create",
                "mongodb",
                "--memory-limit-mb",
                "1024",
                "--wiredtiger-cache-size-gb",
                "0.25",
            ]
        )
        == 0
    )
    assert main(["deployment", "status", "mongodb"]) == 0
    output = capsys.readouterr().out
    assert "Saved container memory limit: 1024 MiB" in output
    assert "Saved WiredTiger cache size: 0.25 GiB" in output
    with pytest.warns(UserWarning, match="requested 2048 MiB, existing 1024 MiB"):
        assert main(["deployment", "create", "mongodb", "--memory-limit-mb", "2048"]) == 0
    assert main(["deployment", "create", "mongodb", "--wiredtiger-cache-size-gb", "nan"]) == 1


def test_cli_unspecified_status(docker, capsys):
    deploy_mongodb()
    main(["deployment", "status", "mongodb"])
    assert capsys.readouterr().out.count("not explicitly saved") == 2
