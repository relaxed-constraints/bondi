# Async Couchbase executor

`AsyncCouchbaseExecutor` provides the same six operations as the MongoDB executor,
using the optional Couchbase SDK. Start the Community container and load the shared
sample data using the [local database guide](local-databases.md).

```sh
uv sync --extra couchbase
```

Query descriptions, serialization and workloads still work without this extra.

## Connect and execute

The example and notebook default to our local Docker URI and credentials, so no
environment variables or `.env` file are needed. For another deployment, override
`COUCHBASE_URI`, `COUCHBASE_USERNAME` and `COUCHBASE_PASSWORD`. These defaults belong
to the teaching examples; the executor itself still requires explicit credentials.
In a notebook or async function:

```python
import os
from dbrtoolkit.couchbase import AsyncCouchbaseExecutor, CouchbaseQuery
from couchbase.n1ql import QueryScanConsistency

query = CouchbaseQuery(
    "SELECT RAW b.name FROM business b WHERE city = $city ORDER BY b.name",
    named_parameters={"city": "Sydney"},
    query_context="demo._default",
)

async with await AsyncCouchbaseExecutor.from_uri(
    os.environ.get("COUCHBASE_URI", "couchbase://127.0.0.1:11210?network=external"),
    username=os.environ.get("COUCHBASE_USERNAME", "Administrator"),
    password=os.environ.get("COUCHBASE_PASSWORD", "dbrtoolkit-local"),
    timeout_seconds=10,
    concurrency=2,
) as executor:
    options = {"scan_consistency": QueryScanConsistency.REQUEST_PLUS, "read_only": True}
    result = await executor.run(query, collect_results=True, query_kwargs=options)
    plan = await executor.explain(query, query_kwargs=options)
    measured = await executor.profile(query, query_kwargs=options)

print(result.documents)  # Three Sydney business names (scalar rows).
print(plan.raw["plan"])  # Native EXPLAIN plan.
print(measured.raw["metrics"])
print(measured.warnings)  # Detailed profiling is unavailable on Community.
```

Unlike MongoDB's factory, `from_uri()` is awaited: it connects and waits up to
30 seconds for the Query service. It closes an owned cluster on context exit or
readiness failure. Alternatively, pass a borrowed `acouchbase.cluster.Cluster` to
the constructor; the caller retains responsibility for closing it. `cluster_kwargs`
passes native `ClusterOptions` other than authentication. Use one event loop and
close only after active calls finish.

## Choose an operation

| Operation | What happens | Result |
| --- | --- | --- |
| `run()` | Execute normally; consume every row; request metrics. | `row_count`, optional `documents`, metadata in `raw`. |
| `explain()` | Prefix the original statement with `EXPLAIN`. | Native plan document in `raw`; no `documents` or `row_count`. |
| `profile()` | Execute with `QueryProfile.TIMINGS`; consume every row. | `row_count`, optional `documents`, metadata including profile in `raw`. |

Couchbase profiling can return real query rows via `collect_results=True`, whereas
MongoDB's explain-based profiling cannot. The toolkit does not issue extra queries
to conceal that difference. Detailed profiling requires server support (tested with
Enterprise 7.6.2). Community retains basic metrics and returns a nonfatal warning
when `executionTimings` is absent. This warning reports missing data, not an edition
detection. Both successful cases have `status == "success"`.

`raw` execution metadata is a JSON-compatible dictionary built from public SDK
accessors: `request_id`, `client_context_id`, `status`, `signature`, `warnings`,
`profile`, and `metrics`. Durations become milliseconds (`elapsed_ms`, `execution_ms`);
count wrappers become integers (`result_count`, `result_size`, `sort_count`,
`mutation_count`, `error_count`, `warning_count`). SDK count accessors default absent
counts to zero; these are SDK metrics, not inferred document/index examinations.
The profile tree is preserved unchanged. Missing metadata sections remain `None`.
This is an SDK metadata representation, not a byte-for-byte HTTP response.

EXPLAIN request metrics measure planning, so they are deliberately not exposed as
underlying-query execution metrics. Native warnings are retained as code/message
pairs in execution metadata and readable strings in `result.warnings`.
`elapsed_ms` on the result is client-observed time through consumption and metadata
collection; connection setup is excluded. Parsing into `QuerySummary` is phase 4.

## Workloads, failures and options

```python
from dbrtoolkit.workload import Workload, WorkloadEntry

workload = Workload([WorkloadEntry(query), WorkloadEntry(query)])
# Inside the executor context:
results = await executor.run_workload(workload)
plans = await executor.explain_workload(workload)
profiles = await executor.profile_workload(workload)
```

All methods share bounded concurrency, input ordering and failure policy. With
`continue_on_error=False`, scheduling stops after observing an error while in-flight
operations finish. Unstarted entries are `None`. With True, remaining entries are
attempted. Expected SDK failures are stored in `.error`; single-query methods raise.
Partial results are discarded. SDK argument errors, programming errors and caller
cancellation propagate after workers are cleaned up. Timeout status recognizes
both ambiguous and unambiguous SDK timeouts and local deadlines.

`timeout_seconds` sets both an SDK query timeout and a local deadline through row
consumption. None leaves the SDK timeout in effect. Inputs are not snapshotted;
do not mutate them during operations.

`query_kwargs` passes native `QueryOptions`, including `scan_consistency`, `read_only`,
`adhoc` and `client_context_id`. SDK defaults apply unless overridden; in particular,
`NOT_BOUNDED` may observe indexes before recent writes arrive. Use `REQUEST_PLUS`
when fresh index contents matter, and account for that wait in measurements.
Bindings, query context, metrics, profile, timeout and serializer are reserved.
The nested SDK `raw` escape hatch is also reserved because it can bypass these
controls. No read-only guard or extra retry policy is imposed by the toolkit.

See the [official SDK query guide](https://docs.couchbase.com/python-sdk/current/howtos/sqlpp-queries-with-sdk.html)
for native options. The implementation is tested with SDK 4.6.3 and both local
Couchbase 7.6.2 editions.

## Tests

Offline SDK-boundary tests need no server:

```sh
uv run --extra couchbase pytest
```

Read-only live tests opt in to initialized demo data. Set
`DBRTOOLKIT_TEST_COUCHBASE_USERNAME` and `DBRTOOLKIT_TEST_COUCHBASE_PASSWORD`, then:

```sh
DBRTOOLKIT_TEST_COUCHBASE_COMMUNITY_URI='couchbase://127.0.0.1:11210?network=external' \
DBRTOOLKIT_TEST_COUCHBASE_ENTERPRISE_URI='couchbase://127.0.0.1:11211?network=external' \
uv run --extra couchbase pytest tests/test_couchbase_executor_live.py
```

Either URI can be omitted to skip that edition. The notebook
`notebooks/couchbase_demo.ipynb` demonstrates all six methods on the same sample data.
