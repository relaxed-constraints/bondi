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

Concurrency defaults to one. Increase it when parallel execution fits the experiment;
use one when measuring isolated query behavior. Results retain input order.
`run()` consumes every row even when `collect_results=False`, the default. Collecting
large result sets retains those rows in memory.

Single-query methods raise database errors. Workload methods capture expected database
errors in each result. With `continue_on_error=False`, scheduling stops after an error;
in-flight operations finish and unstarted entries remain `None`. Programming errors
and interruption propagate. A timeout is reported as `status == "timeout"`.

## Backend timing and native options

### MongoDB

Elapsed milliseconds use a monotonic clock and represent client-observed duration,
including decoding, transfer, full cursor consumption and cleanup. Successful
operation timing excludes validation and scheduler waiting. Captured failure timing
covers the delegated call, including its small validation overhead, and excludes
scheduler waiting. It is not server processing time or total workload wall time.

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

Query fields and generated command structure cannot be overridden, nor can callers
turn off command error checking. Options use native names: find uses `batch_size`,
while aggregate uses `batchSize`. Explain inner options are server command fields,
not cursor-specific Python arguments. Workload calls apply identical options to
every entry; they do not translate options between query kinds. Unknown options
are left to the driver/server. Native options can affect execution and semantics;
the query fingerprint alone does not identify those options or the environment.

The executor imposes no read-only guard; aggregation may write through `$out` or
`$merge`. Database permissions determine access. These methods are not restricted
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
use Yanex's active context when called through a synchronous executor; BONDI does
not depend on Yanex.

### Delivery and concurrency

The callback receives the zero-based **original workload position**, the original
`WorkloadEntry`, and its completed `ExecutionResult`. It runs once for each completed
attempt during normal execution, including captured database errors and timeouts.
No callback runs for an unstarted entry. Results are delivered as they become
available, in observed completion order; the returned list remains in workload
order, with `None` for unstarted entries.

Callbacks are serialized **within each workload call**, even with concurrency above
one. Each worker waits for its callback to finish before claiming another entry.
Other in-flight operations can continue while a callback waits. Callback duration
is excluded from `elapsed_ms` and per-query deadlines, but adds to workload wall
time. There is no separate callback timeout.

The callback receives the same result object that appears in the returned list;
there is no deep copy. Treat entries, queries and results as read-only during the
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
other database operations; use awaitable I/O for asynchronous persistence.

### Failures and cancellation

With `continue_on_error=False`, a captured database failure stops new scheduling,
but existing operations finish and their callbacks are delivered, including the
failed query's callback. With `True`, remaining entries are attempted.

A callback exception aborts the workload regardless of `continue_on_error`. It is
propagated after remaining workers are cancelled and their cleanup finishes; it is
never converted into a database-error result. Programming errors and caller
cancellation also abort the workload. After an abort, pending callbacks are **not
guaranteed**, even for queries whose database operations already finished. No
synthetic cancellation results are created, and the workload call raises rather
than returning a partial list. Previously completed external callback writes are
not rolled back; consumers should design persistence for retries where needed.

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
available independently. Enabling checks adds one probe per run/explain/profile
operation, including workload entries; workload scheduling adds no second probe.

MongoDB sends a real ping using a short PyMongo timeout context and an async
deadline. This is independent of the long query deadline and bounds borrowed
clients too, without modifying or closing them. PyMongo's operation deadline can
override server-selection timeout settings; a short `serverSelectionTimeoutMS`
alone is not a substitute for this check.

Couchbase pings only the Query service, using an explicit SDK timeout and an async
deadline. A nonempty report with all reported Query endpoints healthy is required;
a missing service or any unhealthy endpoint fails conservatively. Management or
KV health alone is insufficient. This does not prove every subsequent query can
succeed or that its collections and permissions are valid.

### Failure policy

With checks enabled, a failed probe or recognized connection/service failure stops
new workload scheduling, even with `continue_on_error=True`. Captured availability
failures use `DatabaseUnavailableError` from `bondi.execution`, with the original
driver exception as `__cause__` where available. Its result status is `"error"`,
not an ordinary query `"timeout"`. A failed probe means unavailable or unresponsive
within the deadline, not proof of a crashed database.

Classification is conservative:

- MongoDB connection failures (including server-selection failures) are availability
  failures; a query's `NetworkTimeout` alone remains a query timeout.
- Couchbase `ServiceUnavailableException` and `MissingConnectionException` are
  availability failures. Ordinary ambiguous/unambiguous query timeouts remain
  query timeouts.
- Syntax errors and server-side execution limits remain query-local failures.
- MongoDB authentication/authorization codes 18/13 and Couchbase
  `AuthenticationException` retain their native errors and stop scheduling when
  checks are enabled.
- Invalid API/SDK configuration and programming errors propagate and cancel/drain
  workers. No retries or automatic restarts are added by BONDI.

Single-query calls retain native mid-query errors; probe failures raise
`DatabaseUnavailableError`. The workload policy classifies captured errors without
performing an extra probe or changing normal mid-query execution handling.

In-flight entries drain and deliver callbacks, including captured failures.
Unstarted entries remain `None` and receive no callback. Draining can take the
remaining execution deadline; stopping scheduling is not immediate cancellation.
Caller cancellation and callback failures retain the existing cancellation/cleanup
rules. A successful probe is only a point-in-time observation; outages or overload
can occur immediately afterward.

### Probe timing

`ExecutionResult.health_check_elapsed_ms` records probe overhead separately
(zero when disabled). `elapsed_ms` excludes the probe for both successful and
captured failed queries; it is zero when preflight prevents query execution.
Captured failure timing otherwise retains the small delegated-call overhead.

The query receives its full `timeout_seconds` after preflight. Total wall time can
include probe time, query time, cleanup and callback time. Async deadlines depend
on cooperative cancellation and cannot interrupt arbitrary blocking Python code.
Connection setup, including Couchbase's factory readiness check, remains separate
from the per-operation health deadline. Client shutdown also retains native driver
behavior: for example, PyMongo may contact the server to end sessions during close
and use its configured client timeouts. A short ping deadline does not bound close().

Checkpointing, paired-backend pipeline aborts and rerun decisions remain consumer
responsibilities. Check the returned results before scheduling another workload.

## Sustained execution

Use [`generate_load()`](load-generation.md) to repeatedly select workload entries
under concurrent load with explicit warm-up, measurement and drain phases.
