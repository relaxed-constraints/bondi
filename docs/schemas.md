# Schema inspection

Inspect fields, types and missing values in Python dictionaries. The parser does
not connect to a database: it describes the documents you supply, not validation
rules or a guarantee about unseen data.

```python
from dbrtoolkit.schema import Schema

schema = Schema.from_documents(
    [{"city": "Sydney", "stars": 4}, {"city": "Sydney", "stars": None}, {"city": "Melbourne"}],
    values="full",
)
print(schema.document_count)  # 3
print(schema["stars"].count)  # 2
print(schema["stars"].missing_count)  # 1
print(schema["city"].types["str"].value_counts)  # Sydney: 2, Melbourne: 1
```

`schema.fields` exposes top-level fields; `schema.flat_fields` exposes all observed
paths. Each field has a `types` mapping whose entries contain counts and optional
values. Null is a present value, distinct from a missing field.

## Choose value retention

| Mode | Retained information |
| --- | --- |
| `none` (default) | Structure and counts only |
| `distinct` | Also retain unique primitive values by type |
| `full` | Also retain each primitive value's frequency |

Use `none` for structural scans of large datasets. Use `distinct` when generating
workloads; `full` also works, but the generator ignores frequencies. Both retaining
modes consume memory proportional to the distinct values retained, not a fixed budget.

## Nested fields and incremental ingestion

```python
schema = Schema(values="none")
schema.update([{"items": [{"price": 10}, {}]}])
schema.update([{"items": [{"price": 20}]}])
price = schema["items.[].price"]
print(price.count, price.missing_count)  # 2, 1
```

Missingness is measured against immediate parent objects. Array-element counts can
exceed the number of root documents. Tuple paths using `ARRAY_ELEMENT` handle keys
that contain literal dots or brackets; see the [reference](reference/schema.md).

## Read from a database

Use a bounded query and pass `result.documents` to `Schema.from_documents`. MongoDB
supports both `MongoFindQuery(target, {}, limit=1000)` and a random sample through
`MongoAggregateQuery(target, [{"$sample": {"size": 1000}}])`.

For Couchbase use `SELECT RAW b FROM ... b LIMIT 1000` so rows are the documents,
not wrappers. `ORDER BY RANDOM() LIMIT 1000` selects random rows but can scan and
sort a large input; it is not equivalent in cost to MongoDB's `$sample`.

Executors collect requested rows in memory. For a full large-collection scan, feed
a synchronous PyMongo cursor directly into the parser:

```python
from pymongo import MongoClient

with MongoClient("mongodb://127.0.0.1:27017") as client:
    with client.demo.business.find({}).batch_size(1000) as documents:
        schema = Schema.from_documents(documents, values="none")
```

The parser consumes iterables incrementally. Follow the
[dataset inspection tutorial](tutorials/inspect-data.md) for an executable notebook.
