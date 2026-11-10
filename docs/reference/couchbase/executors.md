# Couchbase executors

::: bondi.couchbase.CouchbaseExecutor
    options:
      show_root_heading: true
      heading_level: 2
      inherited_members: true

::: bondi.couchbase.AsyncCouchbaseExecutor
    options:
      show_root_heading: true
      heading_level: 2

## Workloads, failures and options


```python
from bondi.workload import Workload, WorkloadEntry

workload = Workload([WorkloadEntry(query), WorkloadEntry(query)])
# Inside the executor context:
results = executor.run_workload(workload)
plans = executor.explain_workload(workload)
profiles = executor.profile_workload(workload)
```

All methods share bounded concurrency, input ordering and failure policy. With
`continue_on_error=False`, scheduling stops after observing an error while in-flight
operations finish. Unstarted entries are `None`. With True, remaining entries are
attempted unless enabled health checks identify availability/access failures. Expected SDK failures are stored in `.error`; single-query methods raise.
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


## Result callback contract

All three workload methods accept `on_result(position, entry, result)`, with a
zero-based workload position and the original entry/result objects. Callbacks are
serialized per call in observed completion order; returned results retain input
order. Each worker waits for callback completion before starting another query.
Callback time is excluded from per-query timing and deadlines.

Synchronous callbacks run on the calling thread and must not return awaitables
or reenter the same executor. Async executors accept regular or awaitable callbacks
on their event loop. Treat callback arguments as read-only. Captured errors/timeouts
receive callbacks, including in-flight results drained after fail-fast scheduling.
Callback exceptions propagate after worker cancellation/cleanup, independent of
`continue_on_error`; pending callbacks are not guaranteed after any abort. Results
remain retained in memory. See the [execution guide](../../executor.md#per-query-result-callbacks)
for examples and full failure/thread behavior.


## Health-check contract

Both synchronous and asynchronous executors expose `ping(timeout_seconds=5)`,
returning None or raising `bondi.execution.DatabaseUnavailableError` on probe
failure. Authentication/configuration errors propagate as documented in the
[health-check guide](../../executor.md#bounded-health-checks).

Constructors/factories accept `health_check_timeout_seconds=None`. A positive
finite value enables one preflight per operation and stops workload scheduling
on availability/access failures regardless of `continue_on_error`. In-flight
entries drain with callbacks, and unstarted entries stay None. Defaults are
unchanged. `ExecutionResult.health_check_elapsed_ms` separates probe overhead
from execution timing; a prevented query has `elapsed_ms=0`.
