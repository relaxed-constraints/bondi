# Synchronous executors

Use `MongoDBExecutor` or `CouchbaseExecutor` in ordinary Python scripts. They
return the same results as their async counterparts without requiring `await`.

```python
from dbrtoolkit.mongodb import MongoCollectionRef, MongoDBExecutor, MongoFindQuery

query = MongoFindQuery(
    target=MongoCollectionRef("demo", "business"),
    filter={"stars": {"$gte": 4}},
)
with MongoDBExecutor.from_uri("mongodb://localhost:27017") as executor:
    result = executor.run(query, collect_results=True)
    print(result.documents)
    plan = executor.explain(query)
    profile = executor.profile(query)
```

The `with` block closes the connection and private event loop even if an operation
raises. Keep it open for all queries in an experiment. Results remain usable afterward.
Explicit cleanup is equally supported:

```python
executor = MongoDBExecutor.from_uri("mongodb://localhost:27017")
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

## Notebooks and resource ownership

Jupyter normally runs an event loop already. Use the async executors with `await`
there. Sync adapters reject calls inside a running loop with an explanatory error.

```python
from dbrtoolkit.mongodb import AsyncMongoDBExecutor

executor = AsyncMongoDBExecutor.from_uri("mongodb://localhost:27017")
result = await executor.run(query)
# In a later cell, when finished:
await executor.close()
```

For Couchbase, the async factory also needs `await`:
`executor = await AsyncCouchbaseExecutor.from_uri(...)`.

Sync adapters own their connections and must be created with `from_uri()`.
They do not accept borrowed clients or existing async executors. Use them only
from their creating thread. Each keeps one private event loop alive for its full
lifetime; there is no background thread or nested event loop.
