# Synchronous executors

Use `MongoExecutor` or `CouchbaseExecutor` in ordinary Python scripts. They
return the same results as their async counterparts without requiring `await`.

```python
from dbrtoolkit.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery

query = MongoFindQuery(
    target=MongoCollectionRef("demo", "business"),
    filter={"stars": {"$gte": 4}},
)
with MongoExecutor.from_uri("mongodb://localhost:27017") as executor:
    result = executor.run(query, collect_results=True)
    print(result.documents)
    plan = executor.explain(query)
    profile = executor.profile(query)
```

The `with` block closes the connection and private event loop even if an operation
raises. Keep it open for all queries in an experiment. Results remain usable afterward.
Explicit cleanup is equally supported:

```python
executor = MongoExecutor.from_uri("mongodb://localhost:27017")
try:
    result = executor.run(query)
finally:
    executor.close()
```

Repeated `close()` calls are harmless; later operations raise an error.

## Couchbase and workloads

Install the optional SDK as described in the [Couchbase guide](couchbase-executor.md).

```python
from dbrtoolkit.couchbase import CouchbaseExecutor, CouchbaseQuery

with CouchbaseExecutor.from_uri(
    "couchbase://localhost",
    username="Administrator",
    password="dbrtoolkit-local",
    concurrency=4,
) as executor:
    result = executor.run(
        CouchbaseQuery(statement="SELECT RAW b FROM demo._default.business AS b LIMIT 3"),
        collect_results=True,
    )
```

Both adapters expose `run`, `explain`, `profile`, `run_workload`,
`explain_workload`, and `profile_workload`, with the same parameters and results
as the async executors. Workload concurrency still applies: the caller waits,
but queries within a workload may execute concurrently. Timeout and error handling
are unchanged. Parse raw responses explicitly with `summarize(result.raw)`.

## Notebooks, interruption and resource ownership

The synchronous classes work in Jupyter too. Each owns a background thread with
one event loop; its client is created, used and closed on that loop. Notebook
calls block until results arrive, while workload queries can still run concurrently.
No nested event loop or notebook patch is needed.

```python
executor = MongoExecutor.from_uri("mongodb://localhost:27017")
result = executor.run(query)
# In a later cell, when finished:
executor.close()
```

Use a with block when possible so exceptions and notebook interrupts also close
the connection. Ctrl+C / notebook interruption cancels the submitted coroutine
and waits for its cleanup before raising KeyboardInterrupt. An interrupt during
close lets cleanup finish before propagating. Cleanup may take time if a driver
is unresponsive; per-operation timeouts remain useful. Client cancellation does
not guarantee an already-submitted server operation stops immediately.

Synchronous executors own their connections and do not accept borrowed clients.
Use them only from the thread where they were created. Explicit close joins the
worker thread and closes its loop; repeated close calls are harmless. Close any
sampling estimators before their executor.

The async executors remain available when callers want to await operations while
doing other work. The synchronous interface is the default for scripts and notebooks.
