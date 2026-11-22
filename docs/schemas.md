# Schema inspection

Inspect fields, types and missing values in Python dictionaries. The parser does
not connect to a database: it describes the documents you supply, not validation
rules or a guarantee about unseen data.

```python
from bondi.schema import Schema

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

## Supported input

Pass decoded Python documents. Parse JSON text before calling
`Schema.from_documents()`.

Objects are dictionaries (including subclasses), arrays are lists. Supported scalars
are `str`, `bool`, `int`, finite `float`, `None`, `bytes`, `datetime`, `date`, finite
`Decimal`, `UUID`, and BSON `ObjectId`, `Int64`, `Binary`. Type names follow Python
class names except `object`, `array`, and `null`. Unsupported BSON types such as
`Decimal128` currently raise `TypeError`; they are not silently normalized.

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
exceed the number of root documents. A field obtained before an `update()` continues to reflect later observations.

You can pass a generator. The parser neither retains nor modifies the source documents. Each
document is validated before accumulation. If a later document or the input iterator
fails, earlier documents remain, but an invalid document contributes no counts.
Nesting beyond 128 levels, cycles, non-string keys and unsupported values are rejected.
Calls are synchronous and not thread-safe; do not modify input during ingestion.

Treat field and type objects as inspection objects and
do not assign their counters or internals. Mapping properties are read-only;
`fields`, `types` and `value_counts` are live views. `flat_fields` and
`primitive_fields` have snapshot keys referencing live field objects; request them
again to discover newly added paths. `.values` is an immutable snapshot.

### Look up a field by path

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

## Read from a database

The following queries use the business collection from the
[demo deployment](deployment.md#demo-data). Choose a query for your backend,
then run it with the corresponding [executor](executor.md).

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

sample_query = CouchbaseQuery("SELECT RAW b FROM `demo`.`_default`.`business` AS b LIMIT 100")
```

`SELECT RAW b` returns whole document bodies rather than `{ "b": ... }` alias wrappers.
This matters because the parser would otherwise infer an extra field named `b`.
As with MongoDB's limit, this is a bounded preview, not random sampling.

### Couchbase: random selection through SQL++

For the current SQL++ executor, random ordering followed by a limit is an option:

```python
sample_query = CouchbaseQuery(
    "SELECT RAW b FROM `demo`.`_default`.`business` AS b ORDER BY RANDOM() LIMIT 100"
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

### Inspect the query results

```python
from bondi.schema import Schema

result = executor.run(sample_query, collect_results=True)
schema = Schema.from_documents(result.documents)
print(schema.document_count)
print(list(schema.primitive_fields))
```

Retrieve whole document bodies: projections change the schema you observe. Save
sampled documents when an experiment must reuse exactly the same input.

### Scan a full collection

Executors collect requested rows in memory. For a full large-collection scan, feed
a synchronous PyMongo cursor directly into the parser:

```python
from pymongo import MongoClient

with MongoClient("mongodb://127.0.0.1:27017") as client:
    with client.demo.business.find({}).batch_size(1000) as documents:
        schema = Schema.from_documents(documents, values="none")
```

Follow the
[dataset inspection tutorial](tutorials.md#inspect-the-schema-of-a-dataset) for a notebook you can run without a database.

## Save and reuse a snapshot

```python
schema.save("schema.json")
restored = Schema.load("schema.json")
restored.update([{"city": "Brisbane", "stars": 5}])
```

Both methods accept strings and path objects. Snapshots preserve document counts,
retention mode, nested observations, missingness and retained values without a
connection or the source documents. Loading produces independent, mutable schema
observations with the same `update()` behavior.

Local field/type order and full-mode value-frequency order are preserved. Global
`flat_fields` and `primitive_fields` order is **not** a persistence guarantee:
loading rebuilds their indexes by depth-first traversal. Distinct-value sets remain
unordered. Values already combined by Python set/counter equality cannot be recovered
as separate original representations.

Parent directories must exist. Saving writes a temporary sibling file, flushes it
and atomically replaces the destination; failed saves preserve the existing artifact.
Do not mutate a schema while saving. Filesystem errors raise `OSError`; invalid
snapshots, unsupported versions and invalid observations on save raise `ValueError`.

### Version-1 format

The file is one UTF-8 JSON object, with these exact top-level members:

```json
{
  "format": "bondi.schema",
  "format_version": 1,
  "document_count": 2,
  "value_mode": "full",
  "fields": [
    {
      "name": "city",
      "count": 2,
      "types": [
        {
          "name": "str",
          "count": 2,
          "values": [{"value": "Melbourne", "count": 2}]
        }
      ]
    }
  ]
}
```

`fields` is an ordered list of records with literal string `name`, integer `count`
and ordered `types`. A type record has `name`, positive `count`, and:

- For `object`, a `fields` list (possibly empty).
- For `array`, an `elements` record with `count` and `types`, but no name. Even
  empty arrays have this record, with zero count and no types.
- For primitives in `none` mode, no additional members.
- For primitives in `distinct` mode, `values: [{"value": payload}, ...]`.
- For primitives in `full` mode, `values: [{"value": payload, "count": n}, ...]`.

Distinct entries are sorted by their encoded representation for stable output.
Parent links, structural paths, missing counts and flat indexes are derived, not
stored. An `elements` relationship identifies an array step without reserving any
literal field name. Ordinary field names such as `$date`, dots, brackets and empty
strings are never interpreted as type wrappers.

The loader rejects unknown or extra members, duplicate JSON keys, duplicate local
field/type/value entries, unsupported types, invalid scalar payloads and inconsistent
counts. Counts must be integers, not booleans. Type counts sum to field counts;
object-field counts cannot exceed parent-object counts; full-mode frequencies sum
to primitive-type counts. Distinct cardinality cannot exceed the type count.
Array-element counts can exceed array counts. The document nesting limit remains
128, with a zero-count synthetic element node allowed beneath an empty array at the
limit.

The format version is independent of the package version. Version 1 readers reject
other versions. Future support changes must provide an explicit compatibility or
migration policy; files do not depend on pickle or Python object layout. There is
no schema fingerprint or byte-identical-file guarantee.

### Scalar encodings and fidelity

Only retained scalar payloads are decoded with PyMongo's **Canonical Extended JSON**.
The surrounding tree uses ordinary JSON. The enclosing type label identifies the
original Python type.

| Type | Payload and restoration |
| --- | --- |
| `null`, `bool`, `str` | Native JSON null, boolean or string |
| `int`, `Int64`, `float` | Canonical `$numberInt`, `$numberLong`, `$numberDouble`; restore the enclosing Python type, including arbitrary-size integers and finite floats |
| `ObjectId` | `$oid` |
| `bytes`, `Binary` | `$binary`; preserve bytes and subtype, restoring subtype-zero `Binary` explicitly |
| `UUID` | `$binary` with standard UUID representation (subtype 4); restore UUID explicitly |
| `date` | `$date` for midnight UTC; reject non-midnight payloads and restore Python `date` |
| `Decimal` | `$numberDecimal` through BSON Decimal128 when sign, digits and exponent survive exactly; otherwise an exact decimal string |
| `datetime` | `{"iso": "2026-11-08T12:00:00.123456+11:00", "fold": 0}` |

Datetime payloads preserve microseconds, naive/aware status, offset and `fold`.
Aware values load with a **fixed-offset timezone**; timezone identity, named-zone
rules and daylight-saving arithmetic are not preserved. This avoids BSON Date's
millisecond precision limit. Comparisons involving ambiguous named-zone times may
also differ after restoration. Scalar types and finite-number restrictions remain
those of `Schema.from_documents()`; this format does not add Decimal128 as an input
type. The loader requires the writer's canonical scalar representation rather than
accepting arbitrary alternate Extended JSON spellings.

### Experiment artifact integration

Consumer projects can use custom artifact callbacks without making Yanex a BONDI
dependency:

```python
# Inside a Yanex experiment:
yanex.save_artifact(schema, "schema.json", saver=Schema.save)
restored = yanex.load_artifact("schema.json", loader=Schema.load)
```

Accessing `Schema.save` through the class leaves the schema argument for Yanex to
supply; no wrapper function or static method is needed.

Artifact dependency selection and sampling remain responsibilities of the consumer.

## Export and validate JSON Schema

Call `to_json_schema()` to get a [Draft 2020-12 JSON Schema](https://json-schema.org/draft/2020-12) as a Python
dictionary. Pass that schema and either one document or a list of documents to
`validate_json_schema()`.

```python
from bondi.schema import Schema, validate_json_schema

documents = [{"items": [{"name": "tea"}]}, {"items": [None, {"name": "coffee"}]}]
rules = Schema.from_documents(documents).to_json_schema()
validate_json_schema(rules, documents)
validate_json_schema(rules, {"items": []})
```

Both calls pass. Every example document has an `items` field, so the schema
requires it. The array can be empty. Each item can be `null` or an object with
a string `name`. Every object in these arrays had a `name`, so an item like
`{}` would fail.

A field can be required even if its value is sometimes `null`. A field that
was missing from some objects is optional. Documents can include extra fields.
If every array at a field was empty, the schema accepts any item type there.
You can also export a saved snapshot, with or without retained values.

Validation checks the schema once per call. It returns `None` if all documents
pass, including for an empty list. An invalid schema raises
`jsonschema.SchemaError`. An invalid document raises `jsonschema.ValidationError`.
The error shows where validation failed. For a list, it also gives the index of
the first failing document, starting at zero. For offline validation, keep all
schema references local.

### Validate MongoDB documents

For BSON values such as `ObjectId`, choose `canonical_extended_json` when you
export the schema. Then use PyMongo to encode the document in the same format
before validating it.

```python
import json
from bson import ObjectId, json_util

document = {"_id": ObjectId()}
rules = Schema.from_documents([document]).to_json_schema(representation="canonical_extended_json")
encoded = json.loads(json_util.dumps(document, json_options=json_util.CANONICAL_JSON_OPTIONS))
validate_json_schema(rules, encoded)
```

For example, if BONDI saw a Python `int`, the ordinary JSON schema accepts
`7`. The canonical schema accepts `{"$numberInt": "7"}` or
`{"$numberLong": "7"}`. If BONDI saw a BSON `Int64`, its canonical schema
accepts only the `$numberLong` form. The validator checks that the wrapped
value is a string. It does not parse the string as a number.

Canonical export also supports floats, `ObjectId`, `datetime`, `bytes`,
BSON `Binary`, and `UUID`. For UUIDs, choose a UUID representation when
encoding with PyMongo. If a type has no supported encoding, export raises
`ValueError` and names the field. This includes Python `date` and `Decimal`
in both modes.
