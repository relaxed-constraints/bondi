# Load datasets

Use `load_data()` to read documents and insert them into MongoDB or Couchbase.
The loader supports local files, Hugging Face datasets and Python iterables.
It does not generate data or run benchmark queries.

Install optional readers with `pip install 'bondi[data,couchbase]'`.
JSONL, CSV and Python iterables need no data extra. JSON arrays, Parquet and Hub sources use optional readers.

## Load a local file

```python
from bondi.data import MongoConnection, load_data

result = load_data(
    "businesses.jsonl",
    target=MongoConnection("mongodb://localhost:27017"),
    database="research",
    collection="businesses",
    id_field="business_id",
)
print(result.destinations)
```

You can pass a BONDI `Deployment` as `target` instead.
The loader opens and closes its own clients. It does not stop the database.
For authenticated MongoDB deployments, pass credentials separately:

```python
import os

connection = MongoConnection(
    "mongodb://localhost:27017/?authSource=admin",
    username="researcher",
    password=os.environ["MONGO_PASSWORD"],
)
```

These fields accept raw strings. Do not percent-encode them.
Supplied fields override the corresponding URI credentials. Omitted fields preserve URI settings.
Set `authSource` in the URI when the user belongs to another authentication database.
Credentials do not appear in the connection repr or load reports.

CSV columns stay strings. JSON files contain an array of documents or one document.
JSONL contains one document per nonempty line. Parquet uses its declared column types.

## Discover datasets

```sh
bondi datasets list
bondi datasets list --json
bondi datasets info adult
bondi datasets load adult --deployment mongodb --database research --splits merge
```

`list` shows a readable table by default. Use `--json` for the complete catalogue metadata in scripts.

The catalogue includes the packaged `demo` and pinned JSynth `adult`, `diabetes` and `electric_vehicles` configurations.
Hub loads record the resolved commit. Registered JSONL files use the direct JSON reader to preserve document structure.
Other Hub datasets use Hugging Face Datasets, which can apply its own schema conversions.
Check those conversions when missing fields and null values matter to your experiment.

## Load Python documents

```python
result = load_data(
    {
        "users": iter([{"_id": "u1", "name": "Alex"}]),
        "bookings": iter([{"_id": "b1", "user_id": "u1"}]),
    },
    target=MongoConnection("mongodb://localhost:27017"),
    database="travel",
    namespace="travel-example-v1",
)
```

Ordinary mappings name collections. Hugging Face `DatasetDict` objects name splits of one collection.
You can also pass a `Dataset` or `IterableDataset`. A declared split on those objects is preserved.
The loader buffers at most `batch_size` documents and tracks duplicate IDs in a temporary SQLite file.
Writers acknowledge documents individually. Progress callbacks run after each buffered batch.
The source must remain unchanged during loading.

## Document IDs

An explicit `id_field` must exist and must not be null. Otherwise the loader preserves `_id`.
If both fields exist, their values must agree. Source IDs can be strings, integers or ObjectIds.
The source field stays in the document. The loader also sets `_id`.

Documents without IDs need a stable namespace. Registered datasets provide one.
Manifests declare one. Anonymous files and Python iterables need `namespace=`.
Generated IDs hash the namespace, logical collection, original split, shard position and row position.
Their format is `gen:` followed by the first 24 lowercase hexadecimal characters of the SHA-256 hash.
For example: `gen:7f3a92c16b04e8d5a0912c77`. Incoming duplicate-ID checks still apply.
This replaces the earlier `bondi-generated:` format. Recreate previously loaded datasets with explicit replacement when adopting the new format.
Upsert does not remove documents with IDs from the earlier format.
Absolute paths and destination addresses do not affect the ID.
Reordering files or rows changes generated IDs. Identical rows remain separate documents.

Couchbase keys hash the type-aware source ID. Integer `123` and string `"123"` therefore have different keys.
The document body retains `_id`, subject to Couchbase type conversion.
The loader does not rewrite references to metadata keys or repair missing foreign keys.

## Write modes and ownership

The default `mode="create"` refuses nonempty target collections.
`mode="upsert"` inserts new IDs and replaces whole documents with matching IDs.
It leaves documents absent from the new source untouched.
Duplicate IDs within the incoming data are errors in every mode.

`mode="replace"` clears only the selected collections. It preserves their indexes.
A nonempty collection must have a matching BONDI ownership marker, or you must pass `allow_unowned=True`.
Use that override only when you intend to remove the existing documents.
Upserting into an unowned nonempty collection does not claim ownership.

BONDI stores markers in a separate `bondi_load_metadata` collection in each database or scope.
This name is reserved. It is not part of your dataset.
BONDI checks destination access, contents and ownership before clearing any selected collection.
These checks do not lock collections or guarantee later write permissions. Do not run concurrent writers during a load.

## Splits

The default `splits="preserve"` adds the split name to the collection name, such as `adult_train`.
Use `split="train"` or a list of names to select splits.
Selecting one split still retains its suffix. Files without declared splits have no suffix.

Use `splits="merge"` to concatenate selected splits into the unsuffixed collection.
This does not deduplicate documents or add a split field.
Explicit IDs must remain unique across merged splits. Generated IDs include the original split name.
A merged load reports counts for each source split.

Manifests define split order. Other split mappings use sorted names.
Shard lists and row order remain unchanged. This does not imply database query order.
Replacing one split does not clear any unselected split.

## Extended JSON and type conversion

`json_mode="plain"` preserves Extended JSON wrappers as ordinary objects.
Use `json_mode="extended"` to decode them with `loads_query_json`.
Decoding does not infer types from ordinary strings. Conversion applies recursively to nested values.

| Value | MongoDB | Couchbase |
| --- | --- | --- |
| Date/time | UTC BSON date | UTC ISO string with milliseconds |
| Date only | ISO date string | ISO date string |
| ObjectId | ObjectId | Hexadecimal string |
| Decimal | Decimal128 when representable | Error, or text with `decimal_mode="string"` |
| Integer | Signed 64-bit range | Exact range from −(2⁵³−1) to 2⁵³−1 |
| Other BSON types | Preserve if BSON supports them | Error |

Both backends reject nonfinite numbers. The loader never silently converts decimals to floats.
Dates use UTC and truncate sub-millisecond precision.
Extended JSON dates decode as UTC. Other naive Python datetimes require `naive_datetimes="utc"`.
Unsupported values produce a field path in the error. The report records conversion counts.

## Couchbase destinations

```python
from bondi.data import CouchbaseConnection

result = load_data(
    "businesses.jsonl",
    target=CouchbaseConnection("couchbase://localhost", "Administrator", password),
    bucket="research",
    bucket_memory_mb=256,
    scope="benchmark",
    collection="businesses",
    id_field="business_id",
)
```

Missing buckets require an explicit quota of at least 100 MiB.
Existing buckets retain their settings. The quota applies to each new bucket, not the entire cluster.
New buckets use zero replicas. The loader creates missing scopes and collections.
Your account needs permissions for each requested operation.
Couchbase 7.6 or later is required for key-value scans used to inspect and clear collections without indexes.
No primary query index is added automatically.

## Multi-collection manifests

A version 1 JSON manifest can describe local or Hub sources:

```json
{
  "version": 1,
  "namespace": "travel-v1",
  "collections": {
    "users": {"source": "users.jsonl", "id_field": "user_id"},
    "bookings": {"source": "bookings.jsonl", "id_field": "booking_id"}
  },
  "index_profiles": {
    "baseline": {
      "mongodb": [{"collection": "bookings", "name": "booking_user",
                   "keys": [["user_id", 1]], "options": {}}],
      "couchbase": [{"collection": "bookings", "name": "booking_user",
                     "keys": ["user_id"]}]
    }
  }
}
```

File paths are relative to the manifest file. Each source can be a file or an ordered list of files.
Use `splits: {"train": "train.jsonl", "test": "test.jsonl"}` instead of `source` for split files.
Use `hf: {"repo_id": "origami-ml/jsynth-data", "config": "adult", "revision": "main"}` for a Hub source.
The loader resolves the revision and records the commit. Pin a commit for repeatable experiments.

Each collection can override `database`, `bucket`, `scope`, `collection`, `bucket_memory_mb` and `id_field`.
These mappings support several databases or buckets in one load.
Conflicting destination names raise an error before writes.

Index profiles are optional metadata supplied by a dataset publisher or experiment author.
Select one with `indexes="baseline"` or `--indexes baseline`.
Definitions refer to logical collection names and apply to each selected split destination.
MongoDB accepts native key pairs and options. Couchbase supports simple field names in this version.
Existing unrelated indexes remain. These indexes do not enforce foreign-key relationships.

## CLI connections

```sh
bondi datasets load businesses.jsonl --deployment mongodb \
  --database research --collection businesses --id-field business_id
bondi datasets load --manifest travel.json --deployment couchbase \
  --bucket research --bucket-memory-mb 256 --scope benchmark --indexes baseline
```

For external systems, use `--connection connection.json` instead of `--deployment`.
MongoDB configuration contains `backend: "mongodb"` and `uri`.
It also accepts optional `username` and `password_env`:

```json
{
  "backend": "mongodb",
  "uri": "mongodb://localhost:27017/?authSource=admin",
  "username": "researcher",
  "password_env": "MONGO_PASSWORD"
}
```

If `password_env` is supplied, that environment variable must exist.
Without it, the CLI leaves the URI password unchanged.

Couchbase configuration contains `backend: "couchbase"`, `uri`, `username` and `password_env`.
The last field names the environment variable containing the password. Keep connection files out of version control.
Use repeated `--split` arguments to select several splits.

## Progress and failures

Pass `on_progress(result)` to receive a snapshot after each acknowledged batch.
Callbacks must return None. `LoadDataResult` records counts, source information, conversion settings and elapsed time.
Callback failures stop the load after completed writes.

`LoadDataError.result` contains partial progress. `uncertain_writes` means a failed write may have reached the server without an acknowledgement.
A failure can leave resources, indexes or partial data in place.
Replacement is destructive and is not atomic across collections or documents.
The loader does not automatically retry, roll back or resume a failed load.

See the [API reference](reference/data.md) and [dataset notebook](tutorials.md#load-datasets-into-mongodb).

### Terminal output

`bondi datasets list` shows a Rich table. Use `--json` for machine-readable
catalogue metadata. The `info` and `load` commands still return plain JSON.
JSON output contains no colour codes, headings or progress messages.
Use `bondi datasets load --help` to inspect all loading options.
