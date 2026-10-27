# Queries and workloads

A workload is an ordered collection of query entries. Entries optionally carry an
integer `pattern_id`, useful for relating generated query instances to a shared shape.

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

business = MongoCollectionRef("demo", "business")
workload = Workload([
    WorkloadEntry(MongoFindQuery(business, {"city": "Sydney"}), pattern_id=0),
    WorkloadEntry(MongoFindQuery(business, {"city": "Melbourne"}), pattern_id=0),
])
print(len(workload))
print(workload[0].query.filter)
```

All entries must use the same backend. MongoDB find and aggregation queries can
coexist; MongoDB and Couchbase queries cannot. The shared `Query` protocol describes
common behavior without translating query languages.

## Save and load

```python
workload.save("workload.jsonl")
restored = Workload.load("workload.jsonl")
assert restored[0].query.fingerprint() == workload[0].query.fingerprint()
```

Each JSONL line stores a version, a native query envelope and a pattern ID. Loading
reconstructs concrete query objects and BSON values where applicable. It does not
connect to a database. Pattern objects and generation statistics are not stored.

The workload copies the entry list but keeps references to entries and queries.
Edits are visible through those references; validation occurs at explicit checkpoints,
including saving and execution. Do not mutate a workload while it is running.

Next: [execute the workload](executor.md) or [generate patterns](workload-generation.md).
See the [reference](reference/queries.md) for custom queries, validation and persistence errors.
