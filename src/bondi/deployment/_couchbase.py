"""Couchbase REST initialization; independent of the optional Python SDK."""

import base64
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request(db, path, data=None, *, method=None, query=False, auth=True, timeout=10):
    headers = {}
    if auth:
        token = base64.b64encode(f"{db.username}:{db.password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    port = db.query_port if query else db.port
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=urlencode(data).encode() if data is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except HTTPError as exc:
        # Never include response bodies or credentials in diagnostics.
        code = exc.code
        exc.close()
        if code in {400, 401, 403}:
            raise ValueError(
                f"Couchbase HTTP {code} for {path}; check configuration/credentials"
            ) from None
        raise RuntimeError(f"Couchbase HTTP {code} for {path}") from None
    except (URLError, TimeoutError, ConnectionError):
        raise RuntimeError(f"Couchbase not reachable at localhost:{port}") from None


def ready(db, *, timeout=5):
    """Require a healthy bucket and a working SQL++ service."""
    topology = request(db, "/pools/default/nodeServices", timeout=timeout)
    nodes = topology.get("nodesExt", [])
    expected = {"mgmt": db.port, "n1ql": db.query_port, "kv": db.kv_port}
    if not nodes or any(
        node.get("alternateAddresses", {}).get("external", {}).get("hostname") != "127.0.0.1"
        or node.get("alternateAddresses", {}).get("external", {}).get("ports") != expected
        or not {"kv", "n1ql", "mgmt"} <= node.get("services", {}).keys()
        for node in nodes
    ):
        raise RuntimeError("Couchbase SDK topology is not ready")
    bucket = request(db, f"/pools/default/buckets/{db.bucket}", timeout=timeout)
    if not bucket.get("nodes") or any(n.get("status") != "healthy" for n in bucket["nodes"]):
        raise RuntimeError("Couchbase bucket is not ready")
    result = request(
        db, "/query/service", {"statement": "SELECT RAW 1"}, query=True, timeout=timeout
    )
    if result.get("status") != "success" or result.get("results") != [1]:
        raise RuntimeError("Couchbase query service is not ready")


def initialize(db, *, deadline):
    """Idempotently initialize a single node; never overwrite existing credentials."""

    def call(path, data=None, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Couchbase initialization timed out")
        return request(db, path, data, timeout=min(10, remaining), **kwargs)

    def wait(operation):
        while True:
            try:
                return operation()
            except RuntimeError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Couchbase initialization timed out") from None
                time.sleep(min(1, remaining))

    pools = wait(lambda: call("/pools"))
    if not pools.get("pools"):
        call(
            "/clusterInit",
            {
                "hostname": "127.0.0.1",
                "username": db.username,
                "password": db.password,
                "clusterName": db.name,
                "services": "kv,n1ql,index",
                "memoryQuota": 512,
                "indexMemoryQuota": 512,
                "indexerStorageMode": "plasma" if db.edition == "enterprise" else "forestdb",
                "port": "SAME",
            },
            auth=False,
        )
    wait(lambda: call("/pools/default"))
    call(
        "/node/controller/setupAlternateAddresses/external",
        {
            "hostname": "127.0.0.1",
            "mgmt": db.port,
            "n1ql": db.query_port,
            "kv": db.kv_port,
        },
        method="PUT",
    )
    buckets = call("/pools/default/buckets")
    if not any(bucket["name"] == db.bucket for bucket in buckets):
        call(
            "/pools/default/buckets",
            {
                "name": db.bucket,
                "bucketType": "couchbase",
                "ramQuotaMB": 256,
                "replicaNumber": 0,
                "storageBackend": "couchstore",
                "flushEnabled": 0,
            },
        )
    wait(lambda: ready(db, timeout=max(0.1, min(5, deadline - time.monotonic()))))
