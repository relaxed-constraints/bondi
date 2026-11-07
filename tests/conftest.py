"""Opt-in, isolated BONDI deployments shared by live suites."""

import os
import socket
from contextlib import ExitStack, contextmanager

import pytest

from bondi.deployment import deploy_couchbase, deploy_mongodb


class LivePorts:
    """Lease free high-numbered ports for this test process, never standard ports."""

    def __init__(self):
        self.claimed = set()

    def claim(self, backend):
        if backend not in {"mongodb", "couchbase"}:
            raise ValueError(f"Unknown port pool: {backend}")
        for slot in range(10):
            ports = (
                (27117 + slot,)
                if backend == "mongodb"
                else (8191 + 10 * slot, 8193 + 10 * slot, 11310 + 10 * slot)
            )
            if self.claimed.intersection(ports):
                continue
            try:
                # Probe the whole group together. Docker still owns the final bind;
                # another process racing us produces a setup failure, never a takeover.
                with ExitStack() as stack:
                    for port in ports:
                        sock = stack.enter_context(socket.socket())
                        sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            self.claimed.update(ports)
            return ports
        raise RuntimeError(f"No free {backend} live-test ports in the dedicated ten-slot pool")


def pytest_collection_modifyitems(items):
    if os.environ.get("BONDI_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="Set BONDI_LIVE=1 to create isolated Docker test deployments")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def live_ports():
    return LivePorts()


@contextmanager
def deployment_pool(registry, live_ports):
    """Lazily create one demo fixture per backend/edition in a private registry."""
    deployments = {}
    with ExitStack() as cleanup:

        def get(backend):
            if os.environ.get("BONDI_LIVE") != "1":
                pytest.skip("Set BONDI_LIVE=1 to create isolated Docker test deployments")
            if backend not in {"mongodb", "community", "enterprise"}:
                raise ValueError(f"Unknown live backend: {backend}")
            if backend in deployments:
                return deployments[backend]
            with pytest.MonkeyPatch.context() as environment:
                environment.setenv("BONDI_DEPLOYMENT_DIR", str(registry))
                if backend == "mongodb":
                    db = deploy_mongodb("live-mongodb", port=live_ports.claim("mongodb")[0])
                else:
                    management, query, kv = live_ports.claim("couchbase")
                    db = deploy_couchbase(
                        f"live-{backend}",
                        edition=backend,
                        management_port=management,
                        query_port=query,
                        kv_port=kv,
                    )
            # Register teardown before loading data/indexes, including setup failures.
            cleanup.callback(db.remove, delete_data=True)
            if backend == "mongodb":
                db.load_demo_data()
            else:
                from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery

                db.load_demo_data(create_primary_index=True)
                with CouchbaseExecutor.from_uri(
                    db.uri, username=db.username, password=db.password, timeout_seconds=60
                ) as executor:
                    executor.run(
                        CouchbaseQuery(
                            "CREATE INDEX city_stars ON "
                            "`demo`.`_default`.`business`(city, stars DESC)"
                        )
                    )
            deployments[backend] = db
            return db

        yield get


@pytest.fixture(scope="session")
def live_deployments(tmp_path_factory, live_ports):
    with deployment_pool(tmp_path_factory.mktemp("live-deployments"), live_ports) as get:
        yield get


@pytest.fixture(scope="session")
def live_mongodb(live_deployments):
    return live_deployments("mongodb")
