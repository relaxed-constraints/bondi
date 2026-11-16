# Index definitions

Define indexes offline, save them, and apply them to explicit collection targets.
Index administration is synchronous and separate from query execution.

## Shared and native definitions

```python
from bondi import FieldIndex
from bondi.mongodb import MongoIndex
from bondi.couchbase import CouchbaseIndex

recent = FieldIndex(
    keys=(("customer_id", 1), ("created_at", -1)),
    name="customer_recent",
)
unique_email = MongoIndex(keys=(("email", 1),), unique=True)
active = MongoIndex(keys=(("customer_id", 1),), partial_filter={"active": True})
tags = CouchbaseIndex(
    keys=(("DISTINCT ARRAY tag FOR tag IN `tags` END", 1),),
    include_missing=True,
    condition="`active` = TRUE",
)
```

`FieldIndex` accepts simple dotted paths (identifier segments containing letters,
digits and underscores, beginning with a letter or underscore). Directions are
integer `1` and `-1`; booleans are rejected. MongoIndex accepts native field names,
but this initial API still limits directions to `1` and `-1`. Text, hashed,
search/vector and clustered indexes are outside this API.

Shared paths preserve native behavior: MongoDB automatically indexes array elements,
whereas Couchbase field indexes can index whole arrays. Couchbase normally excludes
missing leading keys; MongoDB ordinary indexes include missing-field entries.
No data scan, scalar-only guarantee or semantic equivalence is implied.

CouchbaseIndex keys and conditions are **trusted executable SQL++**, not field names
to quote. Array and functional expressions stay native. `include_missing=True`
applies only to the first key. Put direction and missingness in their respective
options, not inside the expression string. MongoIndex additionally supports
`unique`, `sparse`, and `partial_filter`; sparse and partial cannot be combined.

Definitions are mutable. Constructor predicates are defensively copied; later edits
are validated at serialization and creation checkpoints. Structural validation does
not prove server acceptance. Server version, edition and expression restrictions
still apply. No optional Couchbase SDK is needed to define or load indexes.

## Save one definition

```python
from bondi import load_index

recent.save("recent.index.json")
restored = FieldIndex.load("recent.index.json")
unknown_kind = load_index("recent.index.json")
assert restored == unknown_kind
```

Files are UTF-8 JSON with `format_version: 1` and a `kind` discriminator. Class-specific
loads reject a different kind; unknown versions/options fail explicitly. MongoDB
partial predicates use canonical Extended JSON to preserve BSON types. Connection
settings, targets and server status are never persisted. Saving overwrites the named
file; parent directories must exist. File writes are not transactional.

`to_dict()` / `from_dict()` exchange independent JSON-compatible definitions without
file version envelopes. BSON predicates in these mappings use Extended JSON.
Missing names resolve deterministically from the definition (`resolved_name`);
explicit names are passed unchanged and remain subject to server restrictions.

## Group indexes by logical target

```python
from bondi import IndexSet

config = {
    "inventory": [{"fields": ["brandId"]}, {"fields": ["locationId"]}],
    "transactions": [{"keys": [["customerId", 1], ["created_at", -1]]}],
}
indexes = IndexSet.from_dict(config)
indexes.save("indexes.json")
indexes = IndexSet.load("indexes.json")
assert indexes["inventory"][0].keys == (("brandId", 1),)
```

Use `IndexSet.from_dict(config["indexes"])` with an already parsed YAML experiment
config. BONDI does not add a YAML dependency. `fields` is an ascending-key shorthand
for one shared index; several fields in one entry describe one compound index.
Alternatively construct `IndexSet({"inventory": [recent]})` with definition objects.

Explicit config entries accept `kind: field`, `kind: mongodb`, or `kind: couchbase`,
plus `keys`, optional `name`, and the native options above. Omitted kind means field.
`fields` and `keys` are mutually exclusive. `to_dict()` emits explicit canonical
entries, not original shorthand or YAML formatting.

IndexSet preserves target and definition order. Iteration yields target names and
`len(indexes)` counts targets. Constructor inputs are copied; retrieved lists and
objects are mutable. Duplicate explicit names within a target fail validation;
creation also rejects collisions between generated and explicit names. Empty sets
and empty target lists are valid. IndexSet does not silently deduplicate indexes.

## Apply to deployments or external connections

```python
from bondi import MongoConnection
from bondi.mongodb import MongoCollectionRef, create_index, create_indexes

connection = MongoConnection("mongodb://localhost:27017")
name = create_index(
    connection,
    target=MongoCollectionRef("shop", "orders"),
    index=recent,
)
names = create_indexes(
    connection,
    indexes=indexes,
    targets={key: MongoCollectionRef("shop", key) for key in indexes},
    timeout=300,
)
```

A managed `Deployment` can replace the connection argument directly. This reads
its connection settings; it does not start, stop or otherwise modify its lifecycle.
Connection settings are exported from `bondi`; existing `bondi.data` imports remain
supported. These objects are configuration, not open SDK clients.

For Couchbase, install `bondi[couchbase]` and use:

```python
from bondi import CouchbaseConnection
from bondi.couchbase import CouchbaseCollectionRef, create_indexes

connection = CouchbaseConnection("couchbase://localhost", "Administrator", "password")
names = create_indexes(
    connection,
    indexes=indexes,
    targets={key: CouchbaseCollectionRef("research", "shop", key) for key in indexes},
)
```

The target mapping must contain exactly the logical names in the set. Shared-only
sets work with either backend; a native definition for the other backend fails
before any client is opened. Backend references remain explicit so saved logical
names can map to different database/scope layouts in different projects.

Each call owns and closes a client. Batch calls reuse one client and create indexes
in order. Each index gets its own positive finite timeout in seconds. MongoDB waits
for initial build completion; Couchbase consumes the DDL result and waits until
online. Online does not guarantee that concurrent writes are visible. Connection
establishment and teardown are not covered by a whole-batch deadline.

Existing-index conflicts follow native behavior. MongoDB may reuse an identical
index; Couchbase reports an existing name as an error. Nothing is automatically
replaced or dropped. The default ascending MongoDB `_id` definition reuses the
existing `_id_` index after checking its keys. Custom names or filtering for this
built-in index are rejected; a collection without it raises an error. Couchbase
`_id` is an ordinary JSON field index, not a primary query index.

Batch results map logical targets to lists of confirmed names. Validation failures
occur before connection. A server failure during a batch raises
`IndexCreationError`, with `completed`, `target`, `position` (zero-based), and the
original exception as `__cause__`. Creation is non-atomic: earlier indexes remain,
and the failed operation may have created an index or left a build running.
Single-index calls propagate the original exception. Connection-open failures also
propagate directly because no index operation has started.
