---
name: bondi
description: Use BONDI's Python API and CLI for MongoDB, Couchbase and PostgreSQL deployments, native queries, workloads, execution, schema inspection, MongoDB estimation and generation. Also use when developing BONDI itself. Keep research algorithms and experiment pipelines in consumer projects.
---

# BONDI

Help students and researchers use the toolkit and understand the building blocks
they are combining. BONDI preserves native MongoDB queries, Couchbase SQL++ and PostgreSQL SQL;
it is not a query translator or an experiment-tracking framework.

## Choose the workflow

- For library or CLI usage, read [API and CLI](references/api-and-cli.md).
- To find explanations, API contracts or runnable examples, use the
  [documentation and tutorial map](references/documentation-and-tutorials.md).
- Only when changing BONDI itself, read [development](references/development.md).
  Do not apply BONDI's contributor workflow to a student's consumer repository.

Check the project's installed version (for example,
`uv run python -c "from importlib.metadata import version; print(version('bondi'))"`)
and dependency constraints before using an API. PostgreSQL requires BONDI 0.4.2 or newer. Install the
`postgresql` extra for loading, execution and index operations.
Use `deployment.connection` or settings imported from `bondi` for database access.
Executors use `from_connection()`, loaders use `connection=`, and collection
arguments and attributes use `collection`. It includes sustained load generation, pattern selection, workload callbacks,
MongoDB memory limits and executor health checks. Check installed signatures before
using these features. Online documentation can be newer than the installed package.
Inspect matching source when versions differ. Do not upgrade silently.
An installed skill contains these references, not the BONDI checkout or notebooks.

## Teach while helping

Explain the purpose of the BONDI component or important option being used, briefly
and in the context of the user's task. Provide a relevant clickable online guide
or API reference link where it helps the user understand, verify or extend the
solution. Prefer a specific page (and a verified object anchor when useful) over
the documentation homepage. Use the documentation map for real URLs.

For example, when using `collect_results=True`, explain that executors consume
all rows anyway and this option retains the documents, then link to the
[execution guide](https://relaxed-constraints.github.io/bondi/executor/).
When introducing sampling, explain the distinction between estimated matches and
full-population guarantees and link to the estimation guide.

Offer the matching tutorial notebook when the user wants to explore further.
Keep explanations proportional to their experience and request: a short reason
and one or two useful links usually suffice. Do the requested work; do not replace
it with reading assignments, dump every reference, or require a lesson before
proceeding. If working offline, you may supply known links but do not claim to have
verified their current contents. State version differences when material.

## Preserve the toolkit's boundaries

Use synchronous examples by default for teaching and notebooks; use asynchronous
APIs when the application needs them. Keep query forms native, workloads ordered
and single-backend, and missing diagnostic metrics unknown rather than zero.
Keep research algorithms, benchmark orchestration and experiment tracking in
consumer projects. Consult the current roadmap before assuming a capability exists.

## Sustained load generation

Version 0.2.0 adds executor `generate_load()` with `bondi.load` policies
`WeightedRandom`, `UniformRandom`, `Sequential` and `ByPattern`.
`ByPattern` selects a pattern ID, then an existing query instance within that pattern. Check the installed release
before using it. It inherits executor concurrency/error/health options; selection
and positive measurement/drain durations are required. Warm-up defaults to zero.
`on_result` receives one `LoadResult`; `collect_results` retains database documents,
while `return_load_results=False` streams observations without retaining their list.
Drain expiry records unresolved results and requests cooperative cancellation;
no hard process deadline or server-side cancellation guarantee is provided.
See `docs/load-generation.md` in the source checkout.

## Dataset loading

Use `load_file`, `load_documents`, `load_hf_dataset` or `load_hf_repository`
from `bondi.data`. Single-source calls require an exact CollectionRef.
Hub calls combine all splits by default; select a split explicitly when needed.
Hugging Face manages disk caches by default. Pass `streaming=True` or
`--streaming` to read remotely instead. Hub-hosted JSONL preserves original records,
including missing fields and Extended JSON; other formats use HF's prepared cache. For Hugging Face loads, the
default `json_mode="auto"` uses Extended JSON for raw JSONL when the selected
dataset card has the `mongodb-extended-json` tag. For an untagged Extended JSON
export, pass `json_mode="extended"` or `--json-mode extended` explicitly.
Sources can be files, Hub datasets or document iterables. Use a namespace when anonymous sources lack IDs.
Create mode refuses nonempty collections. Replacement explicitly permits clearing the selected collection.
Do not change a user's write mode to bypass a refusal. Report partial writes if a load fails.
See `docs/datasets.md` and `notebooks/dataset_loading.ipynb` in the source checkout.

## CLI command groups

Use `bondi deployment create` to create a deployment. Use
`bondi deployment list|status|start|stop|logs|remove` to manage deployments.
Lifecycle start, stop and remove accept quoted name globs (`*`, `?`, brackets).
Multiple matches show a full table and ask once with default No; `--yes` skips
confirmation. Single-deployment removal still asks. List and preview tables show
Image and Created; older deployments have no creation timestamp and display —.
Use `bondi dataset` for dataset commands. Python deployment helpers include
`deploy_mongodb()`, `deploy_couchbase()` and `deploy_postgresql()`.

Load packaged demo businesses with `bondi.data.load_demo_data(connection=deployment.connection, collection=ref)`
or `bondi dataset load-demo`. Use the dataset loader for all data sources.

## Index definitions

Use `FieldIndex` and `IndexSet` from `bondi`, and native `MongoIndex`,
`CouchbaseIndex` or `PostgresIndex` from their backend modules. Definitions support versioned JSON
`.save()` / `.load()`; `IndexSet.from_dict()` accepts config mappings with
`fields` shorthand. Generic `bondi.create_index()` / `bondi.create_indexes()` dispatch from the
connection settings. Single creation uses a collection reference;
batch creation uses IndexSet collection names and a MongoDB database, Couchbase bucket/scope or PostgreSQL schema. Batch failures expose
completed names through `IndexCreationError`; no rollback is performed. See
[index definitions](https://relaxed-constraints.github.io/bondi/indexes/).
