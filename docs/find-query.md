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

## Collection references from namespaces

When you already have a namespace string, use the alternate constructor:

```python
business = MongoCollectionRef.from_namespace("demo.business")
archive = MongoCollectionRef.from_namespace("demo.business.archive")
assert archive == MongoCollectionRef("demo", "business.archive")
```

Only the first dot separates the database from the collection. Names retain their
case and whitespace. Non-string inputs raise `TypeError`; missing separators,
empty names, and null characters raise `ValueError`. Like direct construction,
this creates no connection and does not check whether the collection exists.

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

Metadata, sort, skip and limit use ordinary JSON. Filters, projections and entire
aggregation pipelines use Canonical Extended JSON to preserve BSON values. Dates
normalize to BSON millisecond precision.

`$regex` / `$options` documents remain query operator dictionaries, including under
`$elemMatch`. They are never decoded as legacy Extended JSON regex values. Native
`bson.Regex` values are encoded with the explicit `$regularExpression` wrapper.
Dates, ObjectIds and other BSON types retain their usual canonical wrappers.
Literal dictionaries indistinguishable from BSON wrappers (for example a literal
`{"$oid": "0123456789abcdef01234567"}`) are rejected on save rather than silently
converted. This also applies inside `$literal` expressions.

New find envelopes use `format_version: 2` for BSON-aware projections. Version-1
find envelopes still load with their original plain-JSON projection semantics.
Ordinary old queries can be saved again as version 2; their fingerprints change
because fingerprints include the serialized version. A legacy projection containing
a literal wrapper-shaped dictionary still loads unchanged, but cannot be saved as
version 2 without resolving that ambiguity. Old readers cannot load version 2.
Aggregation and outer workload envelope versions remain 1.

See [workload persistence](workloads.md) to save many queries, or the
[MongoDB query reference](reference/mongodb/queries.md) for validation and codec details.
