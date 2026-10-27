# Schema inspection

::: bondi.schema.Schema
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.schema.FieldSchema
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.schema.TypeSchema
    options:
      show_root_heading: true
      heading_level: 2

## Array paths and value retention

`ARRAY_ELEMENT` identifies an array-element step in tuple paths, for example
`schema[("tags", ARRAY_ELEMENT)]`. Import it from `bondi.schema`.
`ValueMode` is the literal type `"none" | "distinct" | "full"`.

## Exact paths


```python
from bondi.schema import ARRAY_ELEMENT

schema["items.[].price"]
schema[("items", ARRAY_ELEMENT, "price")]  # Same lookup, without string syntax.
```

Tuple paths distinguish literal keys from structural separators. For a document
containing both `{"a.b": 1}` and `{"a": {"b": 2}}`:

```python
schema[("a.b",)]  # Literal dotted key.
schema[("a", "b")]  # Nested key; equivalent to schema["a.b"].
```

`flat_fields` uses escaped display strings: backslash escapes dots, opening brackets
and backslashes in literal keys. Every displayed key can be passed back to
`schema[path]`. For example, `r"a\.b"` selects the literal dotted key; `r"\[]"`
selects a literal key named `[]`. Empty-string keys remain supported. Unknown paths
raise `KeyError`; no implicit MongoDB-style array traversal occurs.

## Incremental ingestion and ownership

```python
schema = Schema(values="distinct")
schema.update(first_batch)
city = schema["city"]
schema.update(second_batch)
# city now reflects both batches; schema.value_mode remains "distinct".
```

Generators are accepted and source containers are not retained or modified. Each
document is validated before accumulation. If a later document or the input iterator
fails, earlier documents remain, but an invalid document contributes no counts.
Nesting beyond 128 levels, cycles, non-string keys and unsupported values are rejected.
Calls are synchronous and not thread-safe; do not modify input during ingestion.

Field/type objects remain live after updates. Treat them as inspection objects and
do not assign their counters or internals. Mapping properties are read-only;
`fields`, `types` and `value_counts` are live views. `flat_fields` and
`primitive_fields` have snapshot keys referencing live field objects; request them
again to discover newly added paths. `.values` is an immutable snapshot.

## Supported data and database integration

Objects are dictionaries (including subclasses), arrays are lists. Supported scalars
are `str`, `bool`, `int`, finite `float`, `None`, `bytes`, `datetime`, `date`, finite
`Decimal`, `UUID`, and BSON `ObjectId`, `Int64`, `Binary`. Type names follow Python
class names except `object`, `array`, and `null`. Unsupported BSON types such as
`Decimal128` currently raise `TypeError`; they are not silently normalized.

Pass already-decoded documents. JSON text parsing and conversion policies belong
to the caller. The following queries use the shared `demo` data from our
[local Docker setup](../local-databases.md). Use a MongoDB executor for the first two
and a Couchbase executor for the others; see the [MongoDB](../executor.md) and
[Couchbase](../executor.md) connection examples.

### MongoDB: a bounded preview

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery

sample_query = MongoFindQuery(
    MongoCollectionRef("demo", "business"),
    filter={},
    limit=100,
)
```

This returns up to 100 whole documents. A limit alone is not a random sample;
without an explicit sort, do not assume a stable selection or representative coverage.

### MongoDB: random sampling

```python
from bondi.mongodb import MongoAggregateQuery, MongoCollectionRef

sample_query = MongoAggregateQuery(
    MongoCollectionRef("demo", "business"),
    pipeline=[{"$sample": {"size": 100}}],
)
```

MongoDB's [`$sample`](https://www.mongodb.com/docs/v8.0/reference/operator/aggregation/sample/)
selects documents randomly. With `$sample` first, a collection larger than 100 documents
and a requested sample smaller than 5% of the collection, MongoDB can use a
pseudo-random cursor; otherwise sampling can require scanning and a random top-k sort.
The tiny demo collection contains only eight documents, so it cannot supply 100
distinct source documents. Repeated sampling calls need not return the same documents.

### Couchbase: a bounded preview

```python
from bondi.couchbase import CouchbaseQuery

sample_query = CouchbaseQuery(
    "SELECT RAW b FROM `demo`.`_default`.`business` AS b LIMIT 100"
)
```

`SELECT RAW b` returns whole document bodies rather than `{ "b": ... }` alias wrappers.
This matters because the parser would otherwise infer an extra field named `b`.
As with MongoDB's limit, this is a bounded preview, not random sampling.

### Couchbase: random selection through SQL++

For the current SQL++ executor, random ordering followed by a limit is an option:

```python
sample_query = CouchbaseQuery(
    "SELECT RAW b FROM `demo`.`_default`.`business` AS b "
    "ORDER BY RANDOM() LIMIT 100"
)
```

[`RANDOM()`](https://docs.couchbase.com/server/7.6/n1ql/n1ql-language-reference/numericfun.html)
produces pseudo-random numbers. This query is useful for small datasets but may
scan and randomly sort a large candidate set; LIMIT bounds the output, not the
amount of database work. It is not an efficient sampling primitive equivalent to
MongoDB's random-cursor path. This query was checked against both local 7.6.2 editions.

Couchbase also offers a dedicated
[`SamplingScan`](https://docs.couchbase.com/sdk-api/couchbase-python-client/couchbase_api/couchbase_rangescan.html)
with a limit and optional seed, via the SDK's key-value collection scan API.
It is not a SQL++ query operator and is not currently exposed by
`AsyncCouchbaseExecutor`. Supporting that would be a separate sampling feature;
its suitability and statistical properties should be evaluated before adopting it.

### Infer the schema from any of these queries

Inside the corresponding executor context or notebook:

```python
from bondi.schema import Schema

result = executor.run(sample_query, collect_results=True)
schema = Schema.from_documents(result.documents)
print(schema.document_count)
print(list(schema.primitive_fields))
```

Retrieve whole document bodies: projections change the schema you observe. Save
sampled documents when an experiment must reuse exactly the same input. No database
sampling helper, schema persistence, merging, or validation-schema export is
introduced here.

Run `notebooks/schema_demo.ipynb` to explore all modes using a tiny in-memory dataset;
no database or Couchbase SDK is needed.
