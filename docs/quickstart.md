# Quickstart

## Start without a database

[Install BONDI](installation.md) from PyPI, then inspect a small dataset:

```python
from bondi.schema import Schema

schema = Schema.from_documents([{"city": "Sydney", "stars": 4}, {"city": "Melbourne"}])
print(schema.document_count)  # 2
print(schema["stars"].missing_count)  # 1
```

Run this in your project with `uv run python your_script.py`, or use `python` in
an activated environment.

## Execute a query

Get the [release source and teaching resources](installation.md#get-notebooks-and-docker-compose-files)
if you want to use the demo data. This example reads the bundled MongoDB `demo.business` collection. Complete
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

For a longer runnable example using the same demo data, open
`notebooks/workload_demo.ipynb` in Jupyter. It covers single queries, workloads,
profiling, persistence and a deliberate database error.
