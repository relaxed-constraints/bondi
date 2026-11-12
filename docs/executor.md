# Running queries and workloads

Use `MongoExecutor` or `CouchbaseExecutor` in both scripts and notebooks. They manage
connections and expose the same operations for individual queries and workloads.
Start with the [quickstart](quickstart.md) for a complete MongoDB example.

## Connect to Couchbase

Install the optional SDK and create a [Couchbase deployment](deployment.md#couchbase-deployments).
Load your data into `demo._default.business` before running this query.
These credentials are the defaults for a managed local deployment:

```python
from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery

query = CouchbaseQuery("SELECT RAW b FROM `demo`.`_default`.`business` b LIMIT 5")
with CouchbaseExecutor.from_uri(
    "couchbase://127.0.0.1?network=external",
    username="Administrator",
    password="bondi-local",
    timeout_seconds=10,
) as executor:
    result = executor.run(query, collect_results=True)
    print(result.documents)
```

## Execute a workload

Given a `workload` built with the [workload guide](workloads.md):

```python
from bondi.mongodb import MongoExecutor

with MongoExecutor.from_uri(
    "mongodb://127.0.0.1:27017",
    concurrency=4,
    timeout_seconds=30,
    continue_on_error=True,
) as executor:
    results = executor.run_workload(workload)

for entry, result in zip(workload, results):
    if result is None:
        print("Not started")
    elif result.error is not None:
        print(result.status, result.error)
    else:
        print(entry.pattern_id, result.row_count, result.elapsed_ms)
```

Concurrency defaults to one. Increase it when parallel execution fits the experiment. Use one when measuring isolated query behavior. Results retain input order.
`run()` consumes every row even when `collect_results=False`, the default. Collecting
large result sets retains those rows in memory.

Single-query methods raise database errors. Workload methods capture expected database
errors in each result. With `continue_on_error=False`, scheduling stops after an error. In-flight operations finish and unstarted entries remain `None`. Programming errors
and interruption propagate. A timeout is reported as `status == "timeout"`.

## Backend timing and native options

### MongoDB

BONDI measures elapsed milliseconds with a monotonic clock. This clock does not depend on changes to the system time.
The measurement includes transfer, decoding, reading all rows and cleanup.
For successful queries, it excludes input checks and time waiting for a worker.
For captured failures, it includes the delegated call and its small input-check overhead. It still excludes time waiting for a worker.
These values measure time observed by the client. They do not measure server processing time or the total workload duration.

`timeout_seconds` must be positive and finite, or None. A PyMongo timeout context
surrounds the operation and full cursor iteration, sharing one deadline across
batches. None leaves client defaults in effect. Cleanup happens outside an expired
operation deadline and can add time. A client timeout is not a hard interruption of
arbitrary Python computation or proof the server stopped immediately.

#### Native query options

- `run(..., query_kwargs=...)` forwards native PyMongo find/aggregate keyword options.
- `explain(..., query_kwargs=...)` supplies fields inside the native find/aggregate command.
- `explain(..., command_kwargs=...)` supplies outer `Database.command` options.

```python
executor.run(query, query_kwargs={"hint": "stars_1"})
executor.profile(
    query,
    verbosity="executionStats",
    query_kwargs={"hint": "stars_1"},
    command_kwargs={"maxTimeMS": 5000},
)
```

You cannot override query fields or the generated command structure. You cannot disable command error checks. Options use native names: find uses `batch_size`,
while aggregate uses `batchSize`. Explain inner options are server command fields,
not cursor-specific Python arguments. Workload calls apply identical options to
every entry. They do not translate options between query kinds. The driver or server handles unknown options. Native options can affect execution and semantics. The query fingerprint alone does not identify those options or the environment.

The executor does not enforce read-only queries. Aggregation may write through `$out` or `$merge`. Database permissions determine access. These methods are not restricted
to read-only queries merely because they are called run or explain.

### Couchbase

```python
from bondi.workload import Workload, WorkloadEntry

workload = Workload([WorkloadEntry(query), WorkloadEntry(query)])
# Inside the executor context:
results = executor.run_workload(workload)
plans = executor.explain_workload(workload)
profiles = executor.profile_workload(workload)
```

All three methods use the same concurrency limit and failure policy. Their results follow the input order. With
`continue_on_error=False`, scheduling stops after observing an error while in-flight
operations finish. Unstarted entries are `None`. With True, remaining entries are
attempted unless enabled health checks identify availability/access failures. Workload methods store expected SDK failures in `.error`. Single-query methods raise these errors.
BONDI discards partial results. It raises SDK argument errors and programming errors after worker cleanup. Caller cancellation also propagates after cleanup. Timeout status recognizes
both ambiguous and unambiguous SDK timeouts and local deadlines.

`timeout_seconds` sets both an SDK query timeout and a local deadline through row
consumption. None leaves the SDK timeout in effect. Inputs are not snapshotted. Do not mutate them during operations.

`query_kwargs` passes native `QueryOptions`, including `scan_consistency`, `read_only`,
`adhoc` and `client_context_id`. SDK defaults apply unless overridden. In particular,
`NOT_BOUNDED` may observe indexes before recent writes arrive. Use `REQUEST_PLUS`
when fresh index contents matter, and account for that wait in measurements.
You cannot override bindings, query context, metrics, profile, timeout or serializer through `query_kwargs`.
BONDI also rejects the nested SDK `raw` option because it can bypass these controls.
BONDI does not enforce read-only queries or add retries.

See the [official SDK query guide](https://docs.couchbase.com/python-sdk/current/howtos/sqlpp-queries-with-sdk.html)
for native options. The implementation is tested with SDK 4.6.3 and both local
Couchbase 7.6.2 editions.

## Per-query result callbacks

All three workload methods (`run_workload`, `explain_workload`, `profile_workload`)
on MongoDB and Couchbase executors accept keyword-only `on_result`:

```python
from bondi.mongodb import summarize

outcomes = []


def on_result(position, entry, result):
    print(f"Finished query {position + 1}: {result.status}")
    summary = summarize(result.raw) if result.error is None else None
    outcomes.append((position, entry.pattern_id, result.status, summary))
    # Persist a compact outcome here using your experiment project's own format.


# Inside an executor context, with a previously constructed workload:
results = executor.profile_workload(workload, on_result=on_result)
```

Use `bondi.couchbase.summarize` for Couchbase diagnostics. Progress formatting,
artifact storage and experiment policy remain in consumer projects. A callback can
use Yanex's active context when called through a synchronous executor. BONDI does
not depend on Yanex.

### Delivery and concurrency

The callback receives the zero-based **original workload position**, the original
`WorkloadEntry`, and its completed `ExecutionResult`. It runs once for each completed
attempt during normal execution, including captured database errors and timeouts.
No callback runs for an unstarted entry. BONDI calls callbacks as results become available, in observed completion order.
The returned list follows workload order, with `None` for unstarted entries.

BONDI runs one callback at a time **within each workload call**, even with concurrency above one. Each worker waits for its callback to finish before claiming another entry.
Other in-flight operations can continue while a callback waits. `elapsed_ms` and query deadlines exclude callback time. Callbacks still add to the total workload duration. There is no separate callback timeout.

The callback receives the same result object that appears in the returned list. There is no deep copy. Treat entries, queries and results as read-only during the
call. Derive separate summaries rather than changing results. Callbacks do **not**
reduce result retention: all completed results still accumulate in memory.

### Synchronous and asynchronous callbacks

`MongoExecutor` and `CouchbaseExecutor` run ordinary callbacks on the **calling
thread**, while database operations run on their private background event loop.
This preserves caller thread-local state, including an active Yanex experiment.
Async callbacks and callbacks returning awaitables raise `TypeError` on these
synchronous APIs. Calling or closing the same synchronous executor from inside
its callback raises `RuntimeError`, preventing reentrant use.

`AsyncMongoExecutor` and `AsyncCouchbaseExecutor` invoke callbacks on their current
event loop. A callback may return `None` or an awaitable, which is awaited before
another callback runs. A blocking regular callback blocks this event loop, including
other database operations. Use awaitable I/O for asynchronous persistence.

### Failures and cancellation

With `continue_on_error=False`, a captured database failure stops new scheduling,
but existing operations finish and their callbacks are delivered, including the
failed query's callback. With `True`, remaining entries are attempted.

A callback exception aborts the workload regardless of `continue_on_error`. BONDI cancels the remaining workers and waits for cleanup before it raises the exception.
It never converts a callback exception into a database-error result. Programming errors and caller
cancellation also abort the workload. After an abort, pending callbacks are **not
guaranteed**, even for queries whose database operations already finished. No
synthetic cancellation results are created, and the workload call raises rather
than returning a partial list. Previously completed external callback writes are
not rolled back. Consumers should design persistence for retries where needed.

## Resource ownership and notebooks

Prefer `with` blocks so connections close after success, failure or interruption.
For use across notebook cells, create the executor directly and call `close()` when
finished. Synchronous executors own a background event loop, allowing notebook use
without `await`. Calls block the calling thread until complete.

Use the public async executors only when integrating with other asynchronous code.
Connection ownership and method signatures are covered in the
[MongoDB](reference/mongodb/executors.md) and [Couchbase](reference/couchbase/executors.md)
references. Continue with [explain and profile](profiling.md) for diagnostic operations.

## Bounded health checks

Use an explicit probe before starting work, or opt into one before each operation:

```python
from bondi.execution import DatabaseUnavailableError
from bondi.mongodb import MongoExecutor

with MongoExecutor.from_uri(
    "mongodb://localhost:27017/",
    timeout_seconds=600,
    health_check_timeout_seconds=5,
    continue_on_error=True,
) as executor:
    executor.ping(timeout_seconds=5)  # None on success; raises on failure.
    results = executor.run_workload(workload, on_result=checkpoint)
    unavailable = any(
        result is not None and isinstance(result.error, DatabaseUnavailableError)
        for result in results
    )
```

Here `checkpoint(position, entry, result)` is your callback and `workload` is an
existing workload. The same options and `ping()` are available on Couchbase.
Async executors use `await executor.ping(timeout_seconds=5)`.
Timeouts must be positive finite numbers (not booleans).

`health_check_timeout_seconds=None` is the default: no probe is added and
existing error-continuation behavior is unchanged. Explicit `ping()` remains
available independently. With health checks enabled, BONDI probes the database before each run, explain or profile operation.
This includes each workload entry. The workload scheduler does not add a second probe.

MongoDB sends a real ping using a short PyMongo timeout context and an async
deadline. This is independent of the long query deadline and bounds borrowed
clients too, without changing or closing them. PyMongo's operation deadline can
override server-selection timeout settings. A short `serverSelectionTimeoutMS`
alone is not a substitute for this check.

Couchbase pings only the Query service, using an explicit SDK timeout and an async
deadline. A nonempty report with all reported Query endpoints healthy is required. A missing service or any unhealthy endpoint fails conservatively. Management or
KV health alone is insufficient. This does not prove every subsequent query can
succeed or that its collections and permissions are valid.

### Failure policy

With checks enabled, a failed probe or recognized connection/service failure stops
new workload scheduling, even with `continue_on_error=True`. Captured availability
failures use `DatabaseUnavailableError` from `bondi.execution`, with the original
driver exception as `__cause__` where available. Its result status is `"error"`,
not an ordinary query `"timeout"`. A failed probe means unavailable or unresponsive
within the deadline, not proof of a crashed database.

BONDI classifies failures as follows:

- MongoDB connection failures (including server-selection failures) are availability
  failures. A query's `NetworkTimeout` alone remains a query timeout.
- Couchbase `ServiceUnavailableException` and `MissingConnectionException` are
  availability failures. Ordinary ambiguous/unambiguous query timeouts remain
  query timeouts.
- Syntax errors and server-side execution limits remain query-local failures.
- MongoDB authentication/authorization codes 18/13 and Couchbase
  `AuthenticationException` retain their native errors and stop scheduling when
  checks are enabled.
- Invalid API/SDK configuration and programming errors propagate and cancel/drain
  workers. No retries or automatic restarts are added by BONDI.

Single-query calls retain native mid-query errors. Probe failures raise
`DatabaseUnavailableError`. The workload policy classifies captured errors without
performing an extra probe or changing normal mid-query execution handling.

In-flight entries drain and deliver callbacks, including captured failures.
Unstarted entries remain `None` and receive no callback. Draining can take the
remaining execution deadline. Stopping scheduling is not immediate cancellation.
Caller cancellation and callback failures retain the existing cancellation/cleanup
rules. A successful probe is only a point-in-time observation. Outages or overload
can occur immediately afterward.

### Probe timing

`ExecutionResult.health_check_elapsed_ms` records probe overhead separately
(zero when disabled). `elapsed_ms` excludes the probe for both successful and
captured failed queries. It is zero when preflight prevents query execution.
For other captured failures, the elapsed time includes the small overhead of the delegated call.

The query receives its full `timeout_seconds` after preflight. Total wall time can
include probe time, query time, cleanup and callback time. Async deadlines depend
on cooperative cancellation and cannot interrupt arbitrary blocking Python code.
Connection setup, including Couchbase's factory readiness check, remains separate
from the per-operation health deadline. Client shutdown also retains native driver
behavior: for example, PyMongo may contact the server to end sessions during close
and use its configured client timeouts. A short ping deadline does not bound close().

Your experiment code must save progress and decide when to stop related backend runs or repeat experiments. Check the returned results before scheduling another workload.

## Sustained execution

Use [`generate_load()`](load-generation.md) to repeatedly select workload entries
under concurrent load with explicit warm-up, measurement and drain phases.
