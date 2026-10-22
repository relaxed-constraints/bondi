# Find query

`MongoFindQuery` describes a native MongoDB find operation. It does not connect to
MongoDB or execute anything. PyMongo is installed as a required dependency to
provide BSON-aware serialization.

```python
from dbrtoolkit.mongodb import MongoCollectionRef, MongoFindQuery

query = MongoFindQuery(
    target=MongoCollectionRef("research", "businesses"),
    filter={"stars": {"$gte": 4}},
    projection={"name": 1, "stars": 1, "_id": 0},
    sort=(("stars", -1), ("name", 1)),
    limit=20,
)
```

The target and filter are required. Use `filter={}` explicitly for an unrestricted
query. Projection defaults to None, sort to an empty tuple, skip to zero and limit
to None. A supplied limit must be positive; zero is not our spelling for unlimited.
Sort pairs preserve precedence and support integer 1/-1 directions only.

## Why this dataclass is mutable

Unlike `MongoCollectionRef`, this class has no `frozen=True`. You can refine a query
interactively:

```python
query.filter["stars"]["$gte"] = 5
query.limit = 10
```

Its constructor deep-copies filter and projection, including nested dictionaries
and lists. Editing the query therefore leaves the original input documents alone.
Two queries constructed from the same input also have independent documents.
Values must support Python's `deepcopy`; they are not converted through JSON.

```python
predicate = {"stars": {"$gte": 4}}
query = MongoFindQuery(MongoCollectionRef("research", "businesses"), predicate)
query.filter["stars"]["$gte"] = 5
assert predicate["stars"]["$gte"] == 4
```

## Validation and equality

`__post_init__` validates the target, outer document types, sort structure and
pagination bounds, then copies the documents. Booleans are rejected for pagination
and directions even though Python treats bool as an int subclass.

Defensive copying happens **only at construction**. Validation runs at construction,
on explicit `validate()` calls, and before serialization or fingerprinting. Later assignments and
nested edits are ordinary Python operations. Assigning a new dictionary to
`query.filter` shares that dictionary; assigning `query.limit = -1` does not raise.
Call `query.validate()` to check structural constraints again without copying.
Construct a new query when you also need defensive copying.
We do not claim that a constructed query is accepted by MongoDB: operator and BSON
validation are outside this initial class.

The dataclass compares current field values, so modifying a field can change
equality. Queries are intentionally unhashable: they cannot be dictionary keys
or set members. Use `fingerprint()` for a digest of the current serialized representation.

## Reading the code and documentation

The class lives in `src/dbrtoolkit/mongodb/query.py` and is re-exported from
`mongodb/__init__.py`. Its Google-style docstring supplies the
[generated API reference](api.md); its `>>>` example runs under pytest.
This guide explains usage while the docstring specifies the public contract.

## Save, restore and identify a query

```python
from pathlib import Path

path = Path("query.json")
path.write_text(query.to_json(), encoding="utf-8")
restored = MongoFindQuery.from_json(path.read_text(encoding="utf-8"))
assert restored.fingerprint() == query.fingerprint()
```

`to_json()` validates the current query, builds a versioned envelope, and uses
`bson.json_util.dumps()` with Canonical Extended JSON. `from_json()` uses the
matching loader, checks the envelope and reconstructs the query. All fields are
stored, including defaults. Unknown versions, query kinds, extra/missing fields
and duplicate JSON keys are rejected. This loader expects our canonical format,
not arbitrary relaxed JSON exported by another application.

`fingerprint()` computes SHA-256 over the compact JSON representation on each call.
It includes the format version, logical target and every query option. It preserves
native document order and sort precedence; it does not test semantic equivalence.
Different deployments are not identified. Date precision below milliseconds is
not represented and therefore does not change the fingerprint.

### BSON fidelity and limits

Canonical Extended JSON preserves distinctions such as `Int64(1)` versus `1`.
Tests cover object IDs, decimal values, binary subtypes, regexes, timestamps, nested
values and document order. Normalization follows BSON conventions:

- Naive datetimes are interpreted as UTC; aware datetimes convert to UTC.
- Dates load as naive UTC datetimes, with microseconds truncated to milliseconds.
- Binary subtype zero loads as Python bytes; other subtypes remain `Binary`.
- Large Python integers can load as `bson.Int64`.

These are serialized-value guarantees, not preservation of every Python type.
Unsupported Python values raise codec errors. No BSON conversion validates
whether MongoDB accepts a query's operators.

Extended JSON reserves some document shapes for BSON values. Serialization rejects
literal documents that would be decoded as a different kind of object, including
`{"$numberLong": "1"}` and legacy `$regex`/`$options` documents. Use explicit BSON
values where intended, for example:

```python
from bson import Regex

query = MongoFindQuery(
    MongoCollectionRef("research", "businesses"),
    {"name": Regex("^Cafe", "i")},
)
assert MongoFindQuery.from_json(query.to_json()).fingerprint() == query.fingerprint()
```

This format cannot round-trip every possible literal MongoDB document. It raises
instead of silently changing those ambiguous documents. Serialization does not
mutate the original query.

Execution options, hints and database execution remain future steps.
