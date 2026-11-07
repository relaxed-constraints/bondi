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
Native options and connection ownership details are covered in the
[MongoDB](reference/mongodb/executors.md) and [Couchbase](reference/couchbase/executors.md)
references. Continue with [explain and profile](profiling.md) for diagnostic operations.
