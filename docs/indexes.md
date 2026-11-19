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

`FieldIndex` accepts dotted field paths with nonempty segments. Spaces, Unicode,
and punctuation within segments are preserved exactly, including leading or trailing
spaces. For example, `Model Year` and `item.Model Year` are valid. Dots mean nested
field access; literal dots in field names are not represented by shared paths.
Couchbase quotes and escapes each segment; MongoDB receives the original path.
Null characters and empty segments are rejected. Server naming restrictions still
apply. Directions are
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
settings, database/bucket/scope names and server status are never persisted.
Saving overwrites the named file; parent directories must exist. File writes are not transactional.

`to_dict()` / `from_dict()` exchange independent JSON-compatible definitions without
file version envelopes. BSON predicates in these mappings use Extended JSON.
Missing names resolve deterministically from the definition (`resolved_name`);
explicit names are passed unchanged and remain subject to server restrictions.

## Group indexes by collection

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

IndexSet preserves collection and definition order. Iteration yields collection names and
`len(indexes)` counts collections. Constructor inputs are copied; retrieved lists and
objects are mutable. Duplicate explicit names within a collection fail validation;
creation also rejects collisions between generated and explicit names. Empty sets
and empty collection lists are valid. IndexSet does not silently deduplicate indexes.

## Apply to deployments or external connections

```python
from bondi import MongoConnection
from bondi import create_index, create_indexes
from bondi.mongodb import MongoCollectionRef

connection = MongoConnection("mongodb://localhost:27017")
name = create_index(
    connection,
    collection=MongoCollectionRef("shop", "orders"),
    index=recent,
)
names = create_indexes(
    connection,
    indexes=indexes,
    database="shop",
    timeout=300,
)
```

Use `deployment.connection` for a managed database, or construct `MongoConnection`
or `CouchbaseConnection` for an external instance. These objects are settings;
each operation owns and closes its SDK client. See [Connection settings](connections.md).

The top-level functions dispatch from the connection type. They
require `database` for MongoDB or `bucket` and `scope` for Couchbase and reject mixed
namespace arguments before connecting. Collection references must match the backend.
Explicit backend functions are also available as `create_mongo_index`,
`create_mongo_indexes`, `remove_mongo_index`, `remove_mongo_indexes` in `bondi.mongodb`,
and the corresponding `create_couchbase_*` / `remove_couchbase_*` functions in
`bondi.couchbase`.

For Couchbase, install `bondi[couchbase]` and use:

```python
from bondi import CouchbaseConnection
from bondi import create_indexes

connection = CouchbaseConnection("couchbase://localhost", "Administrator", "password")
names = create_indexes(
    connection,
    indexes=indexes,
    bucket="research",
    scope="shop",
)
```

IndexSet keys are collection names. MongoDB batch creation applies them within
one `database`; Couchbase batch creation applies them within one `bucket` and
`scope`. These namespace arguments are required, including for empty sets.
Shared-only sets work with either backend; a native definition for the other
backend fails before any client is opened. The same saved set can be reused in
different databases or scopes without editing it. Single-index creation still
accepts an explicit collection reference.

Each call owns and closes a client. Batch calls reuse one client and create indexes
in order. Each index gets its own positive finite timeout in seconds. MongoDB waits
for initial build completion; Couchbase consumes the DDL result and waits until
online. Online does not guarantee that concurrent writes are visible. Connection
establishment and teardown are not covered by a whole-batch deadline.

Existing-index conflicts follow native behavior. MongoDB may reuse an identical
index; Couchbase reports an existing name as an error. With the default `replace=False`, nothing is automatically
replaced or dropped. The default ascending MongoDB `_id` definition reuses the
existing `_id_` index after checking its keys. Custom names or filtering for this
built-in index are rejected; a collection without it raises an error. Couchbase
`_id` is an ordinary JSON field index, not a primary query index.

Batch results map collection names to lists of confirmed names. Validation failures
occur before connection. A server failure during a batch raises
`IndexCreationError`, with `completed`, `collection` (the collection name),
`position` (zero-based), and the original exception as `__cause__`. Creation is non-atomic: earlier indexes remain,
and the failed operation may have created an index or left a build running.
Single-index calls propagate the original exception. Connection-open failures also
propagate directly because no index operation has started.


## Replace an experiment's index configuration

```python
from bondi import IndexSet
from bondi import create_indexes

names = create_indexes(
    connection,
    database="shop",
    indexes=IndexSet({"orders": [recent], "inventory": []}),
    replace=True,
)
```

`replace=True` first removes **all secondary indexes** on the included collections,
including indexes created outside BONDI, then creates the supplied definitions.
MongoDB's built-in `_id_` index and all Couchbase primary indexes are preserved.
Couchbase uses the same flag with `bucket` and `scope` instead of `database`.
Collections omitted from the set are untouched. An empty collection list clears
its secondary indexes; an entirely empty set touches nothing. For configuration
comparisons, list every collection the experiment controls, even when its desired
index list is empty. Singular `create_index()` has no replacement flag.

All definitions, targets and options are validated before connecting. Every included
collection is inspected before any deletion. All removals finish before creation
starts. Replacement is not atomic: failures can leave old indexes removed and only
part of the new set created. There is no rollback. A server error raises
`IndexCreationError`, whose `removed` map records confirmed removals and `completed`
map records confirmed creations. `phase` identifies `inspect`, `remove` or `create`;
`position` is a definition position during creation and `None` otherwise.
`index_name` identifies a failed removal. The original error is `__cause__`.
A failed operation may have taken effect even when its result was not confirmed.

Replacement enumerates the backend's ordinary collection indexes (MongoDB indexes
and Couchbase SQL++ query indexes). It does not administer separate Search services.
Run without concurrent index administration: enumeration and deletion are separate
operations, and BONDI does not lock the schema. Each inspection, deletion and build
gets its own timeout; there is no whole-batch deadline.

## Remove selected definitions

```python
from bondi import remove_index, remove_indexes
from bondi.mongodb import MongoCollectionRef

removed = remove_index(
    connection,
    collection=MongoCollectionRef("shop", "orders"),
    index=recent,
)
removed_names = remove_indexes(connection, database="shop", indexes=indexes)
```

Couchbase exposes the same functions with its collection reference or bucket/scope.
Removal identifies an index **by its explicit or generated name**, not by comparing
keys or options. Definitions still undergo normal backend validation. If an existing
index with that name has a different definition, it is still selected for removal.
Equivalent indexes under other names are untouched. MongoDB `_id` definitions and
requests naming a Couchbase primary index raise `ValueError`; in a batch, protected
requests are rejected before any deletion.

`remove_index()` returns `True` for a confirmed removal and `False` when absent.
`remove_indexes()` returns collection-to-name lists of confirmed removals. Missing
names are skipped, so cleanup is repeatable. Empty lists remove nothing. Native
errors other than missing-index errors propagate; absent Couchbase collections
may still raise namespace errors. Each call owns and closes one client.

Batch server failures raise `IndexRemovalError` with `completed`, `collection`,
`position`, `phase`, `index_name` and `__cause__`. Inspection failures have no
position or index name. Single-index calls propagate the original error. No rollback
is attempted, and the failing removal may have taken effect. These functions do
not remove collections, documents or deployments.
