# MongoDB queries

Query objects describe operations independently of a connection. A collection
reference contains only a database and collection name; choose the deployment when
creating an executor.

```python
from bondi.mongodb import MongoAggregateQuery, MongoCollectionRef, MongoFindQuery

business = MongoCollectionRef("demo", "business")
query = MongoFindQuery(
    business,
    {"stars": {"$gte": 4}},
    projection={"name": 1, "stars": 1, "_id": 0},
    sort=(("stars", -1), ("name", 1)),
    limit=10,
)
```

Use native MongoDB filter syntax. `sort` is an ordered tuple of pairs; order matters
for compound sorts. Omit `limit` for unlimited results, rather than using zero.

## Aggregation pipelines

```python
pipeline = MongoAggregateQuery(
    business,
    [
        {"$match": {"stars": {"$gte": 4}}},
        {"$group": {"_id": "$city", "businesses": {"$sum": 1}}},
        {"$sort": {"businesses": -1}},
    ],
)
```

The pipeline stays native and ordered. The toolkit validates basic structure;
MongoDB validates operators and expressions. A pipeline can include write stages,
so use database permissions appropriate to your experiment.

## Edit and save a query

```python
query.limit = 20
query.validate()
text = query.to_json()
restored = MongoFindQuery.from_json(text)
assert restored.fingerprint() == query.fingerprint()
```

Queries are mutable. Construction copies filters, projections and pipelines, but
later edits are ordinary mutations. Do not change them during execution.
Fingerprints identify serialized representations, not semantic equivalence.

Metadata and find options use ordinary JSON. Filters and entire aggregation
pipelines use Canonical Extended JSON to preserve BSON values. Find projections
must be JSON-serializable. Dates normalize to BSON millisecond precision.

See [workload persistence](workloads.md) to save many queries, or the
[MongoDB query reference](reference/mongodb/queries.md) for validation and codec details.
