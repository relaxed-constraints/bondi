"""Read-only edition comparison using the optional SDK in an isolated uv environment.

Run after initializing both Compose environments:
uv run --with couchbase==4.6.3 --no-project python scripts/probe_couchbase_profile.py OUTPUT.json

All examples use the synthetic demo collection. Timings are observations, not benchmarks.
"""

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path

import couchbase
from acouchbase.cluster import Cluster
from couchbase.auth import PasswordAuthenticator
from couchbase.diagnostics import ServiceType
from couchbase.n1ql import QueryProfile, QueryScanConsistency
from couchbase.options import ClusterOptions, QueryOptions, WaitUntilReadyOptions

KEYSPACE = "`demo`.`_default`.`business`"
QUERY = f"SELECT b.* FROM {KEYSPACE} b WHERE city = $city AND review_count >= $minimum"
BINDINGS = {"city": "Sydney", "minimum": 100}


def operators(value):
    """Print native counters without claiming they are MongoDB examination counts."""
    if isinstance(value, dict):
        if "#operator" in value:
            yield {key: value[key] for key in ("#operator", "index", "#stats") if key in value}
        for child in value.values():
            yield from operators(child)
    elif isinstance(value, list):
        for child in value:
            yield from operators(child)


async def probe(port, cases):
    cluster = await Cluster.connect(
        f"couchbase://127.0.0.1:{port}?network=external",
        ClusterOptions(PasswordAuthenticator("Administrator", "dbrtoolkit-local")),
    )
    results = {}
    try:
        await cluster.wait_until_ready(
            timedelta(seconds=30), WaitUntilReadyOptions(service_types=[ServiceType.Query])
        )
        for name, statement, profile, bindings in cases:
            result = cluster.query(
                statement,
                QueryOptions(
                    named_parameters=bindings,
                    metrics=True,
                    profile=profile,
                    scan_consistency=QueryScanConsistency.REQUEST_PLUS,
                    read_only=True,
                    timeout=timedelta(seconds=10),
                ),
            )
            rows = [row async for row in result.rows()]
            meta = result.metadata()  # Synchronous after the async iterator is exhausted.
            metrics = meta.metrics()
            results[name] = {
                "statement": statement,
                "rows": rows,
                "status": str(meta.status()),
                "warnings": meta.warnings(),
                "profile": meta.profile(),
                "metrics": {
                    "elapsed_ms": metrics.elapsed_time().total_seconds() * 1000,
                    "execution_ms": metrics.execution_time().total_seconds() * 1000,
                    "result_count": metrics.result_count().value,
                    "result_size": metrics.result_size().value,
                },
            }
            print(name, json.dumps(results[name]["metrics"]), flush=True)
            print("profile fields:", list((meta.profile() or {}).keys()), flush=True)
            for operator in operators(meta.profile() or {}):
                print(json.dumps(operator), flush=True)
    finally:
        await cluster.close()
    return results


async def main(path):
    enterprise = await probe(
        11211,
        [
            ("explain", "EXPLAIN " + QUERY, QueryProfile.OFF, BINDINGS),
            ("ordinary", QUERY, QueryProfile.OFF, BINDINGS),
            ("phases", QUERY, QueryProfile.PHASES, BINDINGS),
            ("timings", QUERY, QueryProfile.TIMINGS, BINDINGS),
            (
                "covering",
                f"SELECT city, stars FROM {KEYSPACE} WHERE city = $city",
                QueryProfile.TIMINGS,
                {"city": "Sydney"},
            ),
            (
                "aggregation",
                f"SELECT city, COUNT(*) AS n FROM {KEYSPACE} GROUP BY city",
                QueryProfile.TIMINGS,
                {},
            ),
        ],
    )
    community = await probe(11210, [("timings", QUERY, QueryProfile.TIMINGS, BINDINGS)])
    output = {"sdk": couchbase.__version__, "enterprise": enterprise, "community": community}
    Path(path).write_text(json.dumps(output, indent=2) + "\n")
    assert enterprise["ordinary"]["rows"] == enterprise["timings"]["rows"]
    assert enterprise["ordinary"]["rows"] == community["timings"]["rows"]
    assert enterprise["timings"]["profile"]["executionTimings"]
    assert enterprise["phases"]["profile"]["phaseCounts"]
    assert enterprise["ordinary"]["profile"] is None
    assert community["timings"]["profile"] is None
    print("Edition comparison passed; raw results saved to", path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    asyncio.run(main(parser.parse_args().output))
