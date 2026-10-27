# Explaining and profiling queries

Choose the operation according to the question you want to answer:

| Method | Purpose |
| --- | --- |
| `run(query)` | Execute normally and measure client-observed elapsed time |
| `explain(query)` | Inspect the planned operation |
| `profile(query)` | Collect execution diagnostics |

All three have matching `*_workload()` methods. Those methods use the same
concurrency and error policy described in [execution](executor.md).

```python
from dbrtoolkit.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery, summarize

query = MongoFindQuery(MongoCollectionRef("demo", "business"), {"city": "Sydney"})
with MongoExecutor.from_uri("mongodb://127.0.0.1:27017") as executor:
    plan = executor.explain(query)
    profile = executor.profile(query)

print(summarize(plan.raw).plan_stages)
print(summarize(profile.raw).execution_time_ms)
```

Parsing is explicit: executors return `ExecutionResult`, and the backend's
`summarize(raw)` function returns a separate `QuerySummary`. Keep `raw` when you need
backend-specific information beyond the shared summary.

## Backend differences

MongoDB `profile()` uses explain with execution statistics. It does not return query
rows or enable the database profiler. Couchbase `profile()` executes the query with
profiling requested, and can also collect its rows. Explain itself is a planning
operation, so its timing is not the underlying query's execution time.

Couchbase Community returns basic execution metrics. Detailed profiling requires
server support, such as the Enterprise evaluation setup in [Local databases](local-databases.md).
A successful request without detailed timings carries a warning; inspect
`result.warnings` rather than assuming every metric will be present.

Profiling measurements are not interchangeable with ordinary execution timings.
See [query summaries](summaries.md) for metric meanings and interpretation.
