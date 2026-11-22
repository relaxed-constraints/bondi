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
supports both `MongoFindQuery(collection, {}, limit=1000)` and a random sample through
`MongoAggregateQuery(collection, [{"$sample": {"size": 1000}}])`.

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
[dataset inspection tutorial](tutorials.md#inspect-the-schema-of-a-dataset) for an executable notebook.

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

Call `to_json_schema()` to get a JSON Schema (Draft 2020-12) as a Python
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
