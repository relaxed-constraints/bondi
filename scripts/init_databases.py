"""Initialize only this repository's running Compose services and verify sample queries.

Run: uv run python scripts/init_databases.py mongodb|couchbase|couchbase-enterprise|all
No Couchbase Python SDK or host database tools are needed.
"""

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
USERNAME = "Administrator"
PASSWORD = "dbrtoolkit-local"
# CLI-selected evaluation environment; "all" continues to mean Community + MongoDB.
ENTERPRISE = False


def host_port(port: int) -> int:
    return {8091: 9091, 8093: 9093, 11210: 11211}.get(port, port) if ENTERPRISE else port


def compose(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / ("compose.enterprise.yaml" if ENTERPRISE else "compose.yaml")),
            *args,
        ],
        cwd=ROOT,
        text=True,
        check=True,
        **kwargs,
    )


def require_container(service: str) -> None:
    """Never fall back to an unrelated database on the host's default port."""
    result = compose("ps", "--status", "running", "-q", service, capture_output=True)
    if not result.stdout.strip():
        raise RuntimeError(f"Start the {service} Compose profile first")
    if service == "couchbase":
        for port in (8091, 8093):
            mapping = compose("port", service, str(port), capture_output=True).stdout.strip()
            if mapping != f"127.0.0.1:{host_port(port)}":
                raise RuntimeError(f"Unexpected Couchbase port mapping: {mapping}")


def request(
    path: str,
    data: dict | None = None,
    *,
    method: str | None = None,
    port: int = 8091,
    auth: bool = True,
):
    headers = {}
    if auth:
        token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    body = urlencode(data).encode() if data is not None else None
    req = Request(
        f"http://127.0.0.1:{host_port(port)}{path}", data=body, headers=headers, method=method
    )
    with urlopen(req, timeout=10) as response:
        payload = response.read()
        return json.loads(payload) if payload else None


def wait_for(description: str, operation, timeout: int = 180):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return operation()
        except HTTPError as error:
            if error.code not in (404, 424, 429, 500, 502, 503, 504):
                raise
            last_error = error
            time.sleep(2)
        except (URLError, TimeoutError, ConnectionError, RuntimeError) as error:
            last_error = error
            time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {description}: {last_error}")


def query(statement: str):
    response = request(
        "/query/service", {"statement": statement, "scan_consistency": "request_plus"}, port=8093
    )
    if response.get("status") != "success":
        raise RuntimeError(f"SQL++ failed: {response.get('errors', response)}")
    return response.get("results", [])


def mongodb(documents: list[dict]) -> None:
    require_container("mongodb")
    # Execute in the named container, never against an existing host MongoDB.
    script = (
        "const documents = "
        + json.dumps(documents)
        + ";\n"
        + """
const target = db.getSiblingDB('demo').business;
for (const doc of documents) {
    target.replaceOne({_id: doc.business_id}, {_id: doc.business_id, ...doc}, {upsert: true});
}
target.createIndex({city: 1, stars: -1}, {name: 'city_stars'});
const rows = target.find({city: 'Sydney', stars: {$gte: 4}}).toArray();
if (!rows.some(row => row.business_id === 'demo-001')) throw new Error('Sample query failed');
const plan = target.find({city: 'Sydney'}).hint('city_stars').explain('executionStats');
if (!plan.executionStats.executionSuccess) throw new Error('Explain failed');
print('MongoDB: sample documents loaded; query and indexed explain verified.');
"""
    )
    compose("exec", "-T", "mongodb", "mongosh", "--quiet", "--eval", script)


def couchbase(documents: list[dict]) -> None:
    require_container("couchbase")
    pools = wait_for("Couchbase management", lambda: request("/pools"))
    if not pools.get("pools"):
        request(
            "/clusterInit",
            {
                "hostname": "127.0.0.1",
                "username": USERNAME,
                "password": PASSWORD,
                "clusterName": "dbrtoolkit-enterprise" if ENTERPRISE else "dbrtoolkit-local",
                "services": "kv,n1ql,index",
                "memoryQuota": 512,
                "indexMemoryQuota": 512,
                "indexerStorageMode": "plasma" if ENTERPRISE else "forestdb",
                "port": "SAME",
            },
            auth=False,
        )
    wait_for("initialized cluster", lambda: request("/pools/default"))
    # SDKs running on macOS need reachable advertised addresses, not the container IP.
    request(
        "/node/controller/setupAlternateAddresses/external",
        {
            "hostname": "127.0.0.1",
            "mgmt": host_port(8091),
            "n1ql": host_port(8093),
            "kv": host_port(11210),
        },
        method="PUT",
    )
    buckets = request("/pools/default/buckets")
    if not any(bucket["name"] == "demo" for bucket in buckets):
        request(
            "/pools/default/buckets",
            {
                "name": "demo",
                "bucketType": "couchbase",
                "ramQuotaMB": 256,
                "replicaNumber": 0,
                "storageBackend": "couchstore",
                "flushEnabled": 0,
            },
        )
    wait_for("query service", lambda: query("SELECT RAW 1"))
    scopes = wait_for("bucket", lambda: request("/pools/default/buckets/demo/scopes"))["scopes"]
    default = next(scope for scope in scopes if scope["name"] == "_default")
    if not any(collection["name"] == "business" for collection in default["collections"]):
        request("/pools/default/buckets/demo/scopes/_default/collections", {"name": "business"})
    keyspace = "`demo`.`_default`.`business`"
    wait_for("collection", lambda: query(f"CREATE PRIMARY INDEX IF NOT EXISTS ON {keyspace}"))
    query(f"CREATE INDEX city_stars IF NOT EXISTS ON {keyspace}(city, stars DESC)")
    values = ", ".join(
        f"({json.dumps(doc['business_id'])}, {json.dumps(doc)})" for doc in documents
    )
    query(f"UPSERT INTO {keyspace} (KEY, VALUE) VALUES {values}")
    rows = query(f"SELECT b.* FROM {keyspace} b WHERE city = 'Sydney' AND stars >= 4")
    if not any(row["business_id"] == "demo-001" for row in rows):
        raise RuntimeError("Sample query failed")
    plan = query(f"EXPLAIN SELECT b.* FROM {keyspace} b WHERE city = 'Sydney'")
    if not plan:
        raise RuntimeError("Explain returned no plan")
    print("Couchbase: sample documents loaded; SQL++ query and explain verified.")


def main() -> None:
    global ENTERPRISE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("mongodb", "couchbase", "couchbase-enterprise", "all"))
    args = parser.parse_args()
    ENTERPRISE = args.backend == "couchbase-enterprise"
    if ENTERPRISE:
        args.backend = "couchbase"
    documents = json.loads((ROOT / "dev" / "business.json").read_text())
    for name, initialize in (("mongodb", mongodb), ("couchbase", couchbase)):
        if args.backend in (name, "all"):
            initialize(documents)


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        raise SystemExit(f"Couchbase HTTP {error.code}: {error.read().decode()}") from error
