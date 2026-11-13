"""Offline checks of live-test port isolation and deployment ownership."""

import os
from unittest.mock import MagicMock

import pytest

from tests import conftest


def fake_sockets(monkeypatch, occupied=()):
    bound = []

    def socket():
        mock = MagicMock()
        mock.__enter__.return_value = mock

        def bind(address):
            bound.append(address[1])
            if address[1] in occupied:
                raise OSError("occupied")

        mock.bind.side_effect = bind
        return mock

    monkeypatch.setattr(conftest.socket, "socket", socket)
    return bound


def test_ports_skip_occupied_groups_and_never_reuse_leases(monkeypatch):
    fake_sockets(monkeypatch, occupied={27117, 8193})
    pool = conftest.LivePorts()
    assert pool.claim("mongodb") == (27118,)
    assert pool.claim("mongodb") == (27119,)
    assert pool.claim("couchbase") == (8201, 8203, 11320)
    assert pool.claim("couchbase") == (8211, 8213, 11330)


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_ports_fail_after_ten_slots(monkeypatch, backend):
    bound = fake_sockets(monkeypatch)
    pool = conftest.LivePorts()
    for _ in range(10):
        pool.claim(backend)
    with pytest.raises(RuntimeError, match="ten-slot pool"):
        pool.claim(backend)
    assert not set(bound).intersection(range(20217, 20228))
    assert not set(bound).intersection({27017, 27018, 8091, 8093, 11210})


def test_pool_reuses_owned_deployment_and_restores_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_LIVE", "1")
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", "user-registry")
    db = MagicMock()
    calls = []

    def deploy(name, **kwargs):
        calls.append((name, kwargs, os.environ["BONDI_DEPLOYMENT_DIR"]))
        return db

    monkeypatch.setattr(conftest, "deploy_mongodb", deploy)
    ports = MagicMock()
    ports.claim.return_value = (27117,)
    with conftest.deployment_pool(tmp_path, ports) as get:
        assert get("mongodb") is get("mongodb") is db
        assert os.environ["BONDI_DEPLOYMENT_DIR"] == "user-registry"
        db.remove.assert_not_called()
    assert calls == [("live-mongodb", {"port": 27117}, str(tmp_path))]
    db.load_demo_data.assert_called_once_with()
    db.remove.assert_called_once_with(keep_data=False)


def test_failed_demo_setup_still_removes_owned_deployment(tmp_path, monkeypatch):
    monkeypatch.setenv("BONDI_LIVE", "1")
    db = MagicMock()
    db.load_demo_data.side_effect = RuntimeError("load failed")
    monkeypatch.setattr(conftest, "deploy_mongodb", lambda *a, **kw: db)
    ports = MagicMock()
    ports.claim.return_value = (27117,)
    with pytest.raises(RuntimeError, match="load failed"):
        with conftest.deployment_pool(tmp_path, ports) as get:
            get("mongodb")
    db.remove.assert_called_once_with(keep_data=False)


def test_pool_requires_opt_in_even_when_requested_directly(tmp_path, monkeypatch):
    monkeypatch.delenv("BONDI_LIVE", raising=False)
    deploy = MagicMock()
    monkeypatch.setattr(conftest, "deploy_mongodb", deploy)
    with conftest.deployment_pool(tmp_path, MagicMock()) as get:
        with pytest.raises(pytest.skip.Exception):
            get("mongodb")
    deploy.assert_not_called()
