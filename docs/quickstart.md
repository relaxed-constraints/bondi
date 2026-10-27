# Quickstart

This example reads the bundled MongoDB `demo.business` collection. Complete
[installation](installation.md) and [database initialization](local-databases.md) first.
Run the code in a script or notebook:

```python
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery

business = MongoCollectionRef("demo", "business")
query = MongoFindQuery(business, {"city": "Sydney"}, limit=5)

with MongoExecutor.from_uri("mongodb://127.0.0.1:27017") as executor:
    result = executor.run(query, collect_results=True)
    print(result.documents)
    print(result.row_count, result.elapsed_ms)
```

A query describes an operation without opening a connection. The executor performs
it and consumes the complete cursor. `collect_results=True` retains the returned
rows; omit it when you only need counts and timing. `elapsed_ms` measures time
observed by the client, not server execution time.

The `with` block closes the executor even when an exception occurs. Alternatively,
create it directly and call `executor.close()` in a `finally` block.

Next: [run a workload](executor.md), [inspect a schema](schemas.md), or
[describe a Couchbase query](couchbase-query.md).
