# Couchbase query

Couchbase uses SQL++ (formerly N1QL): SQL-like statements over JSON documents.
A typical collection path is `bucket.scope.collection`. The statement can refer
to multiple collections, so our query object has no single target collection.

```python
from dbrtoolkit.couchbase import CouchbaseQuery

query = CouchbaseQuery(
    statement="""
        SELECT b.name, b.stars
        FROM `research`.`data`.`businesses` AS b
        WHERE b.stars >= $minimum
        ORDER BY b.stars DESC
        LIMIT 20
    """,
    named_parameters={"minimum": 4},
)
restored = CouchbaseQuery.from_json(query.to_json())
assert restored == query
assert restored.fingerprint() == query.fingerprint()
```

This example describes a query; it does not execute one. No Couchbase SDK or
connection is needed. See the [official SDK query guide](https://docs.couchbase.com/python-sdk/current/howtos/sqlpp-queries-with-sdk.html)
for SQL++ parameters and scope-level execution.

## Four fields

- `statement`: required nonblank text, preserved exactly.
- `named_parameters`: dictionary of JSON values; defaults to an independent empty dict.
- `positional_parameters`: list of JSON values; defaults to an independent empty list.
- `query_context`: optional native context string for resolving collection names.

Named keys conventionally omit the `$` prefix used in the statement. Positional
parameters correspond to placeholders such as `$1` and `$2`. Both styles are
supported, but this toolkit rejects a query using both nonempty styles together.
This is our scope restriction, not a claim about the server.

The context supplies name-resolution information such as bucket and scope. It is
part of query identity and is saved, but its syntax is not parsed. Credentials,
timeouts, consistency and profiling controls belong to later execution configuration.

## Validation and mutation

The class is a mutable dataclass with no public base class. Both parameter
containers are deep-copied on construction. Later edits are ordinary mutations;
`validate()`, `to_json()` and `fingerprint()` check the current state again.
Validation does not copy or modify the query.

Parameters must contain plain JSON types: dicts with string keys, lists, strings,
booleans, integers, finite floats and None. Tuples, dates, bytes and BSON-specific
values are rejected rather than silently converted. Circular references are
rejected. JSON validity does not guarantee that the server supports the exact
numeric range or precision of a value.

Validation checks structure, not SQL++ syntax, placeholder bindings or whether a
statement writes data. An invalid LLM-generated SQL++ candidate can still be saved
and evaluated. Blank output is rejected; raw LLM responses belong in project artifacts.

## Persistence and fingerprints

The version-1 standard JSON envelope contains `format_version`, `query_kind`
(`couchbase.sqlpp`), `statement`, `named_parameters`, `positional_parameters` and
`query_context`. Unlike MongoDB serialization, this does not use Extended JSON.
Unknown/missing/extra fields, duplicate keys and nonfinite numbers are rejected.

`fingerprint()` hashes the compact saved representation with SHA-256. It includes
exact statement/context text and parameter values and order. Changes to SQL++
whitespace or comments change the fingerprint. Parameter dictionary insertion order
also matters: this is representation identity, not semantic equivalence. External
JSON indentation and envelope field order do not affect the reconstructed digest.

Queries are unhashable because they can change. A fingerprint is recomputed on
every call and remains stable through a save/load round trip.

## Reading the implementation

Start with `src/dbrtoolkit/couchbase/query.py`. The dataclass defines the four
fields, `validate()` checks their contract, and the small private `_validate_json`
function traverses nested JSON values. `to_json()` builds the envelope;
`from_json()` checks it; `fingerprint()` hashes it. `couchbase/__init__.py` exposes
the public import. The standard-library JSON implementation remains separate from
the MongoDB BSON helpers.

The [API reference](api.md) is generated from these docstrings. Its `>>>` example
runs with pytest. See [queries and workloads](workloads.md) for the shared Query protocol.
