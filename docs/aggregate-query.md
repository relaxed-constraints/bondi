# Aggregation query

`MongoAggregateQuery` describes an ordered pipeline starting at a collection. It
uses the same collection reference and persistence methods as `MongoFindQuery`.

```python
from dbrtoolkit.mongodb import MongoAggregateQuery, MongoCollectionRef

query = MongoAggregateQuery(
    target=MongoCollectionRef("research", "businesses"),
    pipeline=[
        {"$match": {"stars": {"$gte": 4}}},
        {"$group": {"_id": "$city", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ],
)
restored = MongoAggregateQuery.from_json(query.to_json())
assert restored.fingerprint() == query.fingerprint()
```

## Two fields, no inheritance hierarchy

The dataclass contains only `target` and `pipeline`. Projection, sorting, skipping
and limiting are stages inside the pipeline, where their position is explicit.
References to other collections, including `$lookup` and `$unionWith`, remain in
the native pipeline. Collectionless and database-level targets are outside this
initial contract.

The class lives in `src/dbrtoolkit/mongodb/aggregate.py` and is re-exported from
`dbrtoolkit.mongodb`. It does not inherit from `MongoFindQuery`. Both use private
functions in `_serialization.py` to share Canonical Extended JSON encoding,
envelope checks and ambiguous-document detection. The public methods remain on
the query classes; the shared Query protocol describes their interface without inheritance.

## Mutation and validation

The pipeline is deep-copied at construction, including nested lists and documents.
Later changes are ordinary Python mutations and are not intercepted:

```python
query.pipeline[-1]["$limit"] = 5
query.validate()
```

Validation checks that the target is a `MongoCollectionRef`, the pipeline is a list,
and each top-level stage is a dictionary with exactly one string key beginning
with `$` followed by a nonempty name. An explicitly empty pipeline is permitted.
Stage values can be scalars, documents or arrays. Unknown stage names, argument
semantics and nested pipelines are not validated here. For example, construction
does not establish that MongoDB accepts a given `$limit` argument.

Validation runs at construction and on `validate()`, `to_json()` and `fingerprint()`.
It does not modify or copy the pipeline. The mutable query is unhashable; its
fingerprint is computed from its current serialized representation on each call.

## Persistence

The version-1 envelope has exactly four fields: `format_version`, `query_kind`
(`mongodb.aggregate`), `target` and `pipeline`. Stage order and every native
document's key order are preserved, including compound `$sort` precedence.
Loaders reject the other query kind rather than guessing a conversion.

The [find-query BSON fidelity rules](find-query.md#bson-fidelity-and-limits) apply
here too: date and binary normalization, numeric type preservation, and rejection
of ambiguous literal Extended JSON documents. Formatting changes outside payloads
do not change the reconstructed fingerprint. Fingerprints do not identify semantic
equivalence or the database deployment.

## Representation is separate from execution policy

`$out` and `$merge` can be represented. This class does not claim that a pipeline
is read-only, and it never executes a pipeline. Execution policy will be designed
with the executor. Constructing or serializing a query has no database effects.

See the [API reference](api.md) for signatures and docstrings. The class's `>>>`
example is executed by pytest as well as displayed by mkdocstrings.
