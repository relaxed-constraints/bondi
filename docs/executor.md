# Running queries and workloads

Use `MongoExecutor` or `CouchbaseExecutor` in both scripts and notebooks. They manage
connections and expose the same operations for individual queries and workloads.
Start with the [quickstart](quickstart.md) for a complete MongoDB example.

## Connect to Couchbase

Install the optional SDK and initialize the [local database](local-databases.md).
These credentials are only for the bundled local environment:

```python
from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery

query = CouchbaseQuery("SELECT RAW b FROM `demo`.`_default`.`business` b LIMIT 5")
with CouchbaseExecutor.from_uri(
    "couchbase://127.0.0.1?network=external",
    username="Administrator",
    password="dbrtoolkit-local",
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

## Resource ownership and notebooks

Prefer `with` blocks so connections close after success, failure or interruption.
For use across notebook cells, create the executor directly and call `close()` when
finished. Synchronous executors own a background event loop, allowing notebook use
without `await`. Calls block the calling thread until complete.

Use the public async executors only when integrating with other asynchronous code.
Native options and connection ownership details are covered in the
[MongoDB](reference/mongodb/executors.md) and [Couchbase](reference/couchbase/executors.md)
references. Continue with [explain and profile](profiling.md) for diagnostic operations.
