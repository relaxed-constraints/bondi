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

## Decode external query JSON

Use `loads_query_json` for JSON received from a file, user or model when BSON
values and MongoDB operators must coexist:

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery, loads_query_json

predicate = loads_query_json("""{
  "tags": {"$elemMatch": {"$regex": "^python$", "$options": "i"}},
  "created": {"$gte": {"$date": "2026-01-01T00:00:00Z"}}
}""")
query = MongoFindQuery(MongoCollectionRef("research", "posts"), predicate)
```

The function returns ordinary Python data with decoded BSON types, not a query
object. Objects, arrays and scalars are supported. It shares the query persistence
codec, preserving `$regex`/`$options` dictionaries while decoding explicit
`$regularExpression`, `$date`, `$oid` and other PyMongo-supported type wrappers.
Both canonical and relaxed Extended JSON are accepted; persistence loaders still
require their versioned envelopes and canonical payloads.

Duplicate keys at any depth, malformed JSON/BSON wrappers, bare NaN/Infinity,
floating-point overflow and excessive nesting raise `ValueError`. Non-string
input raises `TypeError`. Explicit Extended JSON `$numberDouble` wrappers can
represent BSON nonfinite values; this is distinct from illegal bare JSON tokens.

There is no MongoDB operator validation, schema validation, output repair or I/O.
Unknown operators remain dictionaries for MongoDB to validate later. Object order
is retained. `$literal` is not an escape from Extended JSON: wrapper-shaped objects
are still decoded as types. Callers needing the original JSON representation for
audit records should retain the text or decode it separately with standard JSON.

## Convert a find query to aggregation

`MongoFindQuery.to_aggregate()` returns an independent `MongoAggregateQuery`
with the same target. It emits `$match`, `$sort`, `$skip`, `$limit`, then `$project`,
omitting empty/default components. For example:

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery

query = MongoFindQuery(
    MongoCollectionRef("demo", "items"),
    {"foo": "bar"},
    sort=(("baz", 1),),
    limit=5,
)
aggregate = query.to_aggregate()
assert aggregate.pipeline == [
    {"$match": {"foo": "bar"}},
    {"$sort": {"baz": 1}},
    {"$limit": 5},
]
```

Conversion validates the current query and deep-copies its payload. It does not
connect to MongoDB. Ordinary inclusion/exclusion projections are supported;
$slice`, `$elemMatch` and positional `$` support is described below. Other
projection forms raise `ValueError`. `$where`, `$near`, `$nearSphere`,
`$natural` sorting, duplicate sort keys and numeric projection path components
also raise clear errors. This is a conservative conversion, not a complete MongoDB
syntax validator. Result ordering among tied sort keys remains unspecified; use a
unique tie-breaker such as `_id` when comparing results.


### Array projections

The conversion supports the following bounded translations (verified against
MongoDB 8.0.16). `$getField` in element matching requires MongoDB 5.0 or newer.

- **`$slice`** on top-level fields accepts an integer (including zero and negative
  values), or `[skip, positive_limit]`. Non-array values remain unchanged; missing
  fields remain missing. Slice-only/exclusion projections use `$set` and, when
  needed, a final exclusion `$project`, preserving other fields. Inclusion
  projections use a computed `$project`.
- **`$elemMatch`** on top-level fields uses `$filter` and keeps the first matching
  element. The field is omitted if there is no match or the input is not an array.
  Exclusion projections preserve unspecified fields using `$set`; combining
  `$slice` and `$elemMatch` without explicit inclusions also preserves them.
  Conditions support scalar `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`
  and `$not`, or conditions on immediate object fields with `$and`, `$or`, `$nor`.
  Operands are finite Python numbers (`int`/`float`), strings, booleans, and null
  (null supports equality and membership, including their negations). Range
  comparisons preserve query type bracketing; object fields preserve implicit
  array matching and missing/null behavior.
- **Positional `$`** on a top-level array supports a sole query filter of the form
  `{array: {"$elemMatch": condition}}`, using the same condition subset. This binds
  all conditions to one element. Other positional filters raise `ValueError`,
  including implicit bindings and filters involving additional fields.

For example:

```python
query = MongoFindQuery(
    MongoCollectionRef("demo", "items"),
    {"scores": {"$elemMatch": {"$gte": 80, "$lt": 90}}},
    projection={"scores.$": 1, "_id": 0},
)
aggregate = query.to_aggregate()
```

Dotted paths for special projections or element-condition fields, numeric path
components, nested `$elemMatch` conditions, regex conditions, object/array literal
operands, computed find projections and ambiguous positional bindings are not
translated. They raise `ValueError` rather than approximating query behavior.
Field order in returned documents is not a conversion guarantee.

Special projections can expand into multiple stages and expression operators.
Statistics over the converted pipeline therefore measure the translated pipeline,
not the number of operators originally written in the find projection.

To run differential tests using an isolated BONDI-managed MongoDB (Docker required):

```sh
BONDI_LIVE=1 uv run pytest tests/test_mongodb_conversion_live.py
```

These tests provision their own deployment and temporary database, then remove
them during teardown.

## Analyze query structure

Use [`query_statistics()`](mongodb-query-statistics.md) for shared, versioned
predicate, operator and stage counts. Find queries are analyzed through
`to_aggregate()`; aggregation queries retain their submitted structure.
