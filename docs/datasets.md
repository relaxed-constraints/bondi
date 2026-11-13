# Load datasets

Choose one source and one exact collection reference.

| Function | Source | Destination |
|---|---|---|
| `load_file` | CSV, JSON, JSONL or Parquet | One collection |
| `load_documents` | Iterable of dictionaries | One collection |
| `load_hf_dataset` | One HF configuration | One collection |
| `load_hf_repository` | All HF configurations | One collection per configuration |

All readers are included in `pip install bondi`. In this repository, use `uv sync`.
CSV and JSONL use standard-library readers. JSON arrays use ijson, Parquet uses
PyArrow, and Hub sources use Hugging Face libraries.
See the [API reference](reference/data.md).

## Load a file

```python
from bondi.data import load_file
from bondi.deployment import get_deployment
from bondi.mongodb import MongoCollectionRef

deployment = get_deployment("notebook-datasets")
result = load_file(
    "dev/business.json",
    target=deployment,
    collection=MongoCollectionRef("demo", "business"),
    id_field="business_id",
)
```

The destination is exactly `demo.business`. The extension selects the reader.
JSON arrays are streamed; a single JSON object is one document. CSV values remain
strings. Parquet uses its declared types. JSONL preserves missing fields.
Duplicate JSON keys are rejected.

```bash
bondi datasets load-file dev/business.json --deployment notebook-datasets --database demo --collection business --id-field business_id
```

Load multiple files with multiple calls. There are no packages, manifests or suffix rules.

## Load documents

```python
from bondi.data import load_documents

load_documents(
    [{"_id": "a", "name": "Harbour Cafe"}, {"_id": "b", "name": "Garden Books"}],
    target=deployment,
    collection=MongoCollectionRef("demo", "shops"),
)
```

Generators and Hugging Face Dataset objects also work. Select a split yourself
before passing data from a DatasetDict.

## Load one Hugging Face dataset

```python
from bondi.data import load_hf_dataset

result = load_hf_dataset(
    "origami-ml/jsynth-data",
    dataset="adult",
    split="train",
    target=deployment,
    collection=MongoCollectionRef("demo", "adult"),
)
```

`dataset` is the HF configuration (subset). Omit it only for a single-config repo.
The collection name never changes. Omit `split` to combine all splits, pass a
string for one, or a list for several. Splits load in sorted order.
No split column is added. Duplicate explicit IDs fail instead of being deduplicated.

```bash
bondi datasets load-hf origami-ml/jsynth-data --dataset adult --split train --deployment notebook-datasets --database demo --collection adult
```

Repeat `--split` to select several; omit it to combine all.
Use `revision="COMMIT"` or `--revision COMMIT` for repeatable sources.
The result records the resolved commit. HF streaming readers can normalize rows to
a shared schema, including filling missing fields with nulls. Load original JSONL
files when field presence must be preserved.

`bondi datasets list` shows suggested configurations. `--json` returns metadata.
`bondi datasets info adult` shows its source and pinned revision.
These suggestions are not source aliases accepted by loading functions.

## Load a repository

```python
from bondi.data import load_hf_repository

results = load_hf_repository(
    "our-org/forum-data",
    target=deployment,
    database="forum",
)
```

Configurations named `users` and `posts` become collections with those exact names.
There is no renaming option. This convention may not fit every HF repository.

```bash
bondi datasets load-hf-repository our-org/forum-data --deployment notebook-datasets --database forum
```

One revision is resolved for all configurations. Names and split selections are
checked before writes. Configurations load sequentially in sorted order.
An optional split selection applies to every configuration; a missing split fails
before writes. Success returns a dictionary of results keyed by configuration.
On failure, earlier writes remain. `LoadDataError.result` includes completed
collections and the failed collection. Progress callbacks report the current
collection only. This is not a transaction.

## Couchbase and external connections

```python
from bondi.couchbase import CouchbaseCollectionRef

load_file(
    "dev/business.json",
    target=couchbase_deployment,
    collection=CouchbaseCollectionRef("demo", "_default", "business"),
    id_field="business_id",
)
```

CLI destinations use `--bucket demo --scope _default --collection business`.
References must match the target backend. Repository loading takes `bucket` and
`scope` instead of `database`. Missing scopes and collections are created.
A missing bucket requires `bucket_memory_mb=256` or `--bucket-memory-mb 256`
(at least 100 MiB). Existing quotas stay unchanged. Range scans require Server 7.6+.

```python
from bondi.data import MongoConnection, CouchbaseConnection

mongo = MongoConnection("mongodb://localhost/", username="researcher", password=password)
couchbase = CouchbaseConnection(
    "couchbase://localhost", username="Administrator", password=password
)
```

These connection objects can replace a deployment as `target`.
MongoDB credentials are optional and override corresponding URI credentials.
Representations and reports omit credentials.

CLI commands accept `--deployment NAME` or `--connection connection.json`:

```json
{"backend": "mongodb", "uri": "mongodb://localhost/?authSource=admin",
 "username": "researcher", "password_env": "MONGO_PASSWORD"}
```

For Couchbase, set backend `couchbase` and supply its URI, username and password_env.

## IDs and write modes

Preserve `_id` or select an `id_field`. Local sources without either require a
`namespace` for generated IDs. HF sources use repository and configuration identity.
Generated IDs use `gen:` plus 24 hexadecimal characters, based on namespace,
logical collection, original split and row position. Row reordering changes IDs.
HF IDs stay stable when loading a split alone or with others at the same contents.
Couchbase uses a separate type-aware physical document key.

| Mode | Behaviour |
|---|---|
| `create` (default) | Require empty or absent collection |
| `replace` | Clear selected collection, preserving indexes |
| `upsert` | Replace matching IDs, insert new IDs, retain other documents |

Replacement explicitly permits deletion. No ownership metadata is stored.
Duplicate incoming IDs fail in every mode. Repository mode applies per collection.

## Types and progress

`json_mode="extended"` decodes Extended JSON through `loads_query_json`.
MongoDB retains BSON values. Couchbase stores dates as UTC ISO strings and
ObjectIds as strings. Couchbase decimals require `decimal_mode="string"`.
Naive datetimes require `naive_datetimes="utc"`. Nonfinite numbers fail.
Couchbase integers must fit its safe JSON range.
Explicit JSON dates without offsets are interpreted as UTC.

`batch_size` bounds buffering; writes are acknowledged individually.
A synchronous `on_progress` callback receives an independent `LoadDataResult`
after each batch and must return None.
Failures have no rollback or retry. `LoadDataError.result` reports acknowledged
writes and uncertain write outcomes. Do not modify sources or write concurrently.
Create indexes separately through database APIs.
CLI loads return plain JSON; errors go to stderr.
