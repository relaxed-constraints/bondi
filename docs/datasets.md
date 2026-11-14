# Loading datasets

BONDI loads data from local files and Hugging Face into MongoDB and Couchbase deployments.
You can use the CLI or Python API.
You can also load Python dictionaries directly.

Start your database before loading data.
See [Database deployment](deployment.md) if you need to create one.
A plain BONDI installation includes file readers and Hugging Face support.
Couchbase loading also requires `bondi[couchbase]`.

## Load the packaged demo

BONDI includes eight fictional businesses. No download or source checkout is needed.

```sh
bondi dataset load-demo --deployment mongo-demo --database demo --collection business
```

```python
from bondi.data import load_demo_data
from bondi.deployment import get_deployment
from bondi.mongodb import MongoCollectionRef

result = load_demo_data(
    target=get_deployment("mongo-demo"),
    collection=MongoCollectionRef("demo", "business"),
)
print(result.destinations)  # {"demo.business": 8}
```

For Couchbase, install `bondi[couchbase]` and use a Couchbase collection reference:

```python
from bondi.couchbase import CouchbaseCollectionRef

result = load_demo_data(
    target=get_deployment("cb-demo"),
    collection=CouchbaseCollectionRef("demo", "_default", "business"),
)
```

```sh
bondi dataset load-demo --deployment cb-demo --bucket demo --collection business
```

The destination must be empty by default. To reload, use `mode="upsert"` in
Python or `--mode upsert` in the CLI. This replaces matching business IDs and
keeps other documents. Use `replace` to clear the collection first.
The helper uses `business_id` for stable IDs and returns `LoadDataResult`.
It accepts the same targets and options as `load_documents()`, including explicit
connections and progress callbacks. It does not start databases or create query indexes.

For the Couchbase query examples, create a primary index after loading:

```python
from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery

deployment = get_deployment("cb-demo")
with CouchbaseExecutor.from_uri(
    deployment.uri, username=deployment.username, password=deployment.password
) as executor:
    executor.run(CouchbaseQuery(
        "CREATE PRIMARY INDEX IF NOT EXISTS ON `demo`.`_default`.`business`"
    ))
```

See [the API reference](reference/data.md#bondi.data.load_demo_data) for details.

## Load a file

This example loads `dev/business.json` from the BONDI checkout into `demo.business`.
It uses the running deployment named `notebook-datasets`.

### Command line

Run this command from the repository root:

```sh
bondi dataset load-file dev/business.json \
  --deployment notebook-datasets \
  --database demo --collection business \
  --id-field business_id
```

The database is `demo` and the collection is `business`.
The `id-field` option uses each document's `business_id` as its ID.

### Python API

```python
from bondi.data import load_file
from bondi.deployment import get_deployment
from bondi.mongodb import MongoCollectionRef

deployment = get_deployment("notebook-datasets")
business = MongoCollectionRef("demo", "business")

result = load_file(
    "dev/business.json",
    target=deployment,
    collection=business,
    id_field="business_id",
)
print(result.destinations)  # {"demo.business": 8}
```

`target` selects the server connection.
`collection` gives the exact destination.
`get_deployment()` reads saved settings but does not start a stopped database.

The same function accepts CSV, JSON, JSONL and Parquet files.
The filename extension selects the reader.
To load several files, call `load_file` once for each destination.

| Format | How BONDI reads it |
|---|---|
| CSV | Values remain strings |
| JSON | An array supplies documents. A single object supplies one document |
| JSONL | Each nonempty line supplies one document. Missing fields remain absent |
| Parquet | Values use the file's declared types |

BONDI streams JSON arrays and rejects duplicate JSON keys.

## Load Python documents

Use `load_documents` when the data is already in Python:

```python
from bondi.data import load_documents

result = load_documents(
    [{"_id": "a", "name": "Harbour Cafe"}, {"_id": "b", "name": "Garden Books"}],
    target=deployment,
    collection=MongoCollectionRef("demo", "shops"),
)
print(result.destinations)
```

The loader preserves existing `_id` values.
Generators and Hugging Face Dataset objects also work.
For a DatasetDict, select a split before passing its documents to this function.

## Load a Hugging Face dataset

A Hugging Face repository can contain several datasets, called configurations or subsets.
Use `dataset` to select one.

This example loads Adult into `demo.adult`.
It combines all available splits by default:

```sh
bondi dataset load-hf origami-ml/jsynth-data \
  --dataset adult \
  --deployment notebook-datasets \
  --database demo --collection adult
```

```python
from bondi.data import load_hf_dataset

result = load_hf_dataset(
    "origami-ml/jsynth-data",
    dataset="adult",
    target=deployment,
    collection=MongoCollectionRef("demo", "adult"),
)
print(result.destinations)
```

You can omit `dataset` only when the repository has one configuration.
The collection name stays exactly as specified.

### Select splits

To load only the training split, add `--split train`:

```sh
bondi dataset load-hf origami-ml/jsynth-data \
  --dataset adult --split train \
  --deployment notebook-datasets \
  --database demo --collection adult_train
```

In Python, pass `split="train"`.
To select several splits, repeat `--split` or pass a list:

```python
result = load_hf_dataset(
    "origami-ml/jsynth-data",
    dataset="adult",
    split=["train", "test"],
    target=deployment,
    collection=MongoCollectionRef("demo", "adult_selected"),
)
```

Selected splits load into one collection in sorted split order.
The loader does not add a split field or a collection suffix.
It does not remove duplicate rows.
Duplicate explicit document IDs cause an error.

### Dataset versions

You do not need to find a commit hash before loading.
By default, BONDI uses the repository's current `main` revision.
It records the resolved commit in `result.sources`.

For a repeatable source, supply `revision` in Python or `--revision` in the CLI.
You can use a branch, tag or commit.
A commit identifies the exact source version.

### Find suggested datasets

```sh
bondi dataset list
bondi dataset info adult
```

The list shows suggested Hub configurations.
The info command shows the repository, configuration and a pinned revision.
Use those source details with `load-hf`.
The suggestion name itself is not a source alias.
Add `--json` to the list command for machine-readable metadata.

Hugging Face readers can adjust documents to a shared schema.
For example, they can fill missing fields with nulls.
Load original JSONL files when missing fields must remain absent.

## Load a Hugging Face repository

Use `load_hf_repository` to load every configuration into a collection with the same name.
For example, configurations named `users` and `posts` become `forum.users` and `forum.posts`.

The following examples use a placeholder repository, `our-org/forum-data`.
Replace it with your repository ID:

```sh
bondi dataset load-hf-repository our-org/forum-data \
  --deployment notebook-datasets --database forum
```

```python
from bondi.data import load_hf_repository

results = load_hf_repository(
    "our-org/forum-data",
    target=deployment,
    database="forum",
)
for dataset_name, result in results.items():
    print(dataset_name, result.destinations)
```

Collection names come directly from configuration names.
To choose other names, call `load_hf_dataset` separately for each configuration.

BONDI resolves one revision for the whole repository.
It checks collection names and split selections before writing.
Configurations then load sequentially in sorted name order.

By default, each collection combines all splits from its configuration.
An explicit split selection applies to every configuration.
A missing split causes an error before any writes.

This operation is not a transaction.
If a later collection fails, earlier writes remain.
See [Progress and failures](#progress-and-failures) for result details.

## Load into Couchbase

The source functions work with either backend.
For Couchbase, identify the bucket, scope and collection:

```python
from bondi.couchbase import CouchbaseCollectionRef

couchbase = get_deployment("cb-demo")
result = load_file(
    "dev/business.json",
    target=couchbase,
    collection=CouchbaseCollectionRef("demo", "_default", "business"),
    id_field="business_id",
)
print(result.destinations)  # {"demo._default.business": 8}
```

```sh
bondi dataset load-file dev/business.json \
  --deployment cb-demo \
  --bucket demo --scope _default --collection business \
  --id-field business_id
```

Use a collection reference that matches the target backend.
For repository loading, supply `bucket` and `scope` instead of `database`.

BONDI creates missing scopes and collections.
Creating a bucket also requires a memory quota of at least 100 MiB.
For example, pass `bucket_memory_mb=256` or `--bucket-memory-mb 256`.
Existing bucket quotas stay unchanged.
Loading uses range scans and requires Couchbase Server 7.6 or later.

## Load into an external database

You do not need a BONDI-managed deployment.
Pass an explicit connection as `target`:

```python
from bondi.data import MongoConnection

target = MongoConnection(
    "mongodb://localhost/?authSource=admin",
    username="researcher",
    password=password,
)
load_file(
    "dev/business.json",
    target=target,
    collection=MongoCollectionRef("demo", "business"),
    id_field="business_id",
)
```

Supply the `password` variable from your own credential source.
MongoDB username and password are optional.
Explicit credentials override the corresponding values in the URI.

For Couchbase, use `CouchbaseConnection`:

```python
from bondi.data import CouchbaseConnection

target = CouchbaseConnection(
    "couchbase://localhost",
    username="Administrator",
    password=password,
)
```

Connection representations and load reports omit credentials.

### CLI connection files

Use `--connection connection.json` instead of `--deployment NAME`.
A MongoDB connection file can contain:

```json
{
  "backend": "mongodb",
  "uri": "mongodb://localhost/?authSource=admin",
  "username": "researcher",
  "password_env": "MONGO_PASSWORD"
}
```

Set `MONGO_PASSWORD` in the environment before running the command.
For Couchbase, use backend `couchbase` with its URI, username and `password_env`.

## Document IDs

BONDI needs an ID for each document.
It uses the following rules:

1. If you supply `id_field`, BONDI uses that field as `_id`.
2. Otherwise, it preserves an existing `_id`.
3. If neither exists, it generates an ID from the source namespace and row position.

For local files and Python documents, supply a namespace when IDs are missing:

```python
load_documents(
    [{"city": "Sydney"}, {"city": "Melbourne"}],
    target=deployment,
    collection=MongoCollectionRef("demo", "cities"),
    namespace="my-cities",
)
```

The namespace is a stable label for your source.
It is not a database or collection name.
Hugging Face sources use their repository and configuration identity by default.

Generated IDs start with `gen:` and contain 24 hexadecimal characters.
They depend on the namespace, logical collection, original split and row position.
Changing row order changes generated IDs.
For unchanged Hub data, loading a split alone or with other splits preserves its generated IDs.

Couchbase uses a separate physical document key that distinguishes ID types.
The converted `_id` also remains in the stored document.

## Load into an existing collection

The default mode is `create`:

| Mode | Behaviour |
|---|---|
| `create` | Require an empty or absent collection |
| `replace` | Clear the selected collection, preserve its indexes, then load |
| `upsert` | Replace matching IDs, insert new IDs and retain other documents |

Use `mode="replace"` in Python or `--mode replace` in the CLI to reload a collection.
Selecting replacement explicitly permits deleting its existing documents.
BONDI does not store ownership metadata.
Duplicate incoming IDs fail in every mode.

For repository loading, the mode applies to each selected collection.
It does not clear unrelated collections in the database.
Create indexes separately through the database APIs.

### Replacing Couchbase collections

If a collection is missing, the loader creates it and writes the documents.
It does not scan a collection it just created to delete old documents.
If another process creates the collection first, the creation conflict fails the load.

For an existing collection, replacement scans and deletes its documents before writing.
A scan cleanup failure does not hide the original scan or deletion error.
Loads are not atomic. Do not write to the destination concurrently.

## Type conversion

Plain JSON is the default.
Use `json_mode="extended"` or `--json-mode extended` to decode Extended JSON wrappers.
BONDI uses `loads_query_json` for this conversion.

| Value | MongoDB | Couchbase |
|---|---|---|
| BSON values | Retain supported BSON types | Convert supported types to JSON |
| Datetime | Store a BSON date | Store a UTC ISO string |
| ObjectId | Retain ObjectId | Store a string |
| Decimal | Store Decimal128 | Require `decimal_mode="string"` |

A naive datetime has no timezone.
Use `naive_datetimes="utc"` to interpret native naive datetimes as UTC.
Otherwise, they cause an error.
Explicit JSON dates without offsets use UTC.

Nonfinite numbers cause an error.
Couchbase integers must fit the exact JSON integer range, from `-(2**53 - 1)` to `2**53 - 1`.

## Progress and failures

Every load returns a `LoadDataResult`.
Its `destinations` field counts acknowledged writes using dotted names:

- MongoDB: `database.collection`.
- Couchbase: `bucket.scope.collection`.

The result also records source details, original split counts and type conversions.

Use `on_progress` to report progress during a Python load:

```python
def report_progress(result):
    print(result.destinations)


result = load_file(
    "dev/business.json",
    target=deployment,
    collection=business,
    id_field="business_id",
    mode="replace",
    batch_size=1000,
    on_progress=report_progress,
)
```

`batch_size` limits buffered documents.
The writer waits for acknowledgement of each document separately.
After each batch, the callback receives an independent result snapshot.
The callback must be synchronous and return `None`.

Loads do not roll back or retry automatically.
`LoadDataError.result` records acknowledged writes and any uncertain write outcome.
For repository loading, it includes completed collections and the failed collection.
Repository progress callbacks describe only the current collection.

Do not modify source files or write to the target concurrently during loading.
CLI load commands return plain JSON.
Errors go to stderr.

See the [dataset API reference](reference/data.md) for signatures and return types.
