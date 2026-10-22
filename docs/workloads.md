# Queries and workloads

A query describes a database operation. A workload entry associates a query with
optional pattern membership. A workload organizes entries in order and checks that
they all use the same backend.

```python
from dbrtoolkit.mongodb import MongoAggregateQuery, MongoCollectionRef, MongoFindQuery
from dbrtoolkit.workload import Workload, WorkloadEntry

target = MongoCollectionRef("research", "businesses")
query = MongoFindQuery(target, {"stars": {"$gte": 4}})
workload = Workload(
    [
        WorkloadEntry(query, pattern_id=0),
        WorkloadEntry(MongoAggregateQuery(target, [{"$limit": 10}])),
    ]
)
assert len(workload) == 2
workload.validate()
```

## Query: a structural interface

`dbrtoolkit.query.Query` is a Protocol declaring `backend`, `validate()`, `to_json()`
and `fingerprint()`. Native classes satisfy it without inheriting from it. They
need no common filter, pipeline or statement. Loading remains on concrete classes;
no generic loader is introduced here.

Each native class declares its backend with `ClassVar[str]`, so it is not a
constructor argument or dataclass field. MongoDB find and aggregation both use
`mongodb`; SQL++ uses `couchbase`. These identifiers do not alter saved envelopes
or existing fingerprints.

Annotations describe the contract for readers and type checkers, not runtime
validation. No static type checker is configured yet. WorkloadEntry checks the
backend and callable members and invokes query.validate(). These runtime checks
cannot prove custom signatures or serialization correctness.

## WorkloadEntry: a reference plus an optional integer

An entry retains its query reference and optional nonnegative integer `pattern_id`.
Booleans are rejected. None means no recorded pattern association. IDs are local
to the originating workload/pattern collection, not list positions or globally
unique identifiers. We do not yet implement or validate a pattern registry.
Combining independently generated pattern collections will require explicit ID
collision handling when that functionality is designed. No weights are implemented.

## Workload: shallow list ownership

The constructor requires a list of entries (or defaults to an empty list). It makes
its own list but retains the entry and query references. Order and duplicates are
preserved. Iteration yields entries, integer indexing returns an entry, and slicing
returns a plain shallow list of entry references.

```python
entry = WorkloadEntry(query)
source = [entry, entry]
workload = Workload(source)
source.clear()
assert len(workload) == 2
query.limit = 5
assert workload[0].query.limit == workload[1].query.limit == 5
```

Mutating a shared entry or query is visible everywhere it is referenced. For
independent contents, explicitly use `copy.deepcopy(workload)`. No implicit query
cloning happens in entries or workloads. These mutable dataclasses are unhashable.

## Validation is a checkpoint

Construction and explicit `validate()` check every entry and its query, and then
require all backends to match. Different named MongoDB databases or collections
are allowed. Mixing MongoDB and Couchbase is rejected with the incompatible entry's
zero-based index. An empty workload is valid.

Later mutations are not intercepted. Revalidate after edits; a previous validation
does not establish a permanent invariant. No connections or serialization calls
are made during workload validation.

The code lives in `src/dbrtoolkit/query.py` and `src/dbrtoolkit/workload.py`. See the
[API reference](api.md) for signatures. Persistence, generic loading, generation,
sampling, splitting and execution are separate future steps.
