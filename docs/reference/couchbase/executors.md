# Couchbase executors

::: dbrtoolkit.couchbase.CouchbaseExecutor
    options:
      show_root_heading: true
      heading_level: 2
      inherited_members: true

::: dbrtoolkit.couchbase.AsyncCouchbaseExecutor
    options:
      show_root_heading: true
      heading_level: 2

## Workloads, failures and options


```python
from dbrtoolkit.workload import Workload, WorkloadEntry

workload = Workload([WorkloadEntry(query), WorkloadEntry(query)])
# Inside the executor context:
results = executor.run_workload(workload)
plans = executor.explain_workload(workload)
profiles = executor.profile_workload(workload)
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

