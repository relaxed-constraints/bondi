# API and CLI

## Environment and deployment

In a consumer uv project, install with `uv add bondi`, or
`uv add 'bondi[couchbase]'` when executing Couchbase queries. Python 3.11+ is
required. Respect existing version pins. The CLI manages local deployments; query
execution, schema inspection, estimation and generation are Python APIs.

Use managed deployments with Docker and Compose v2 running on the same machine:

```sh
uv run bondi deployment create mongodb --name lesson --port 27019
uv run bondi dataset load-demo --deployment lesson --database demo --collection business
uv run bondi deployment status lesson
uv run bondi deployment stop lesson
uv run bondi deployment start lesson
```

Choose an unused name and port; do not assume a student's existing deployment is
disposable. Deployments start empty. Use `bondi.data.load_demo_data(connection=deployment.connection,
collection=ref)` or `bondi dataset load-demo` to load eight fictional businesses.
Use a MongoCollectionRef, CouchbaseCollectionRef or PostgresCollectionRef for the exact destination.
The default create mode requires an empty collection. Use mode="upsert" or
`--mode upsert` to reload matching business IDs and keep other documents.
The result is LoadDataResult. Deployment handles do not load data.
For Couchbase, specify `--bucket demo --collection business` instead of
`--database demo --collection business`. Install `bondi[couchbase]`.
Create query indexes separately. Demo loading creates no indexes.

Inspect `uv run bondi --help` and subcommand help for installed CLI options.
`python -m bondi` is also supported. Python equivalents live in
`bondi.deployment`: `deploy_mongodb`, `deploy_couchbase`, `deploy_postgresql`, `get_deployment`
and `list_deployments`. A deployment handle exposes `connection` settings and
lifecycle methods; loading a handle does not start the database.

Closing an executor does not stop Docker. CLI `bondi deployment remove NAME` deletes data
and configuration by default, with confirmation; `--keep-data` preserves them.
Python `deployment.remove()` also deletes data and configuration by default.
Use `keep_data=True` to retain them. Match cleanup to the user's intended data ownership.
Use the managed API/CLI rather than legacy repository Compose scripts.

[Deployment guide](https://relaxed-constraints.github.io/bondi/deployment/)

### PostgreSQL (0.4.2+)

Run these commands from a BONDI checkout with PostgreSQL support and Docker running:

```sh
uv run --extra postgresql bondi deployment create postgresql --name pg-demo --database research
uv run --extra postgresql bondi dataset load-demo --deployment pg-demo --schema demo --collection business
```

The connection selects the database. Within it, `PostgresCollectionRef("demo", "business")`
selects a schema and table. Each managed row stores a typed text primary key
(`document_id`) and a JSONB object (`doc`). Inside the document, dates and
ObjectIds become strings and exact decimals remain JSON numbers.

```python
from bondi.deployment import get_deployment
from bondi.postgresql import PostgresExecutor, PostgresQuery, summarize

query = PostgresQuery("SELECT doc FROM demo.business WHERE doc ->> 'city' = %s", ["Sydney"])
with PostgresExecutor.from_connection(get_deployment("pg-demo").connection) as executor:
    result = executor.run(query, collect_results=True)
    businesses = [row["doc"] for row in result.documents]
    summary = summarize(executor.profile(query).raw)
```

Psycopg 3 is the Python driver. Bind positional values with `%s`. Use
`AsyncPostgresExecutor` in async applications. `run()` streams the standalone
SELECT and counts all rows. Collected rows use SQL column labels as keys.
`explain()` returns the estimated plan. `profile()` runs the same SQL with
`EXPLAIN ANALYZE` and returns the measured plan. Use the backend's `summarize()`
to map either JSON plan to the shared summary.

### Deployment selection and creation time (0.3.4+)

Start, stop and remove accept case-sensitive name globs such as
`bondi deployment stop "lesson-*"`. Quote patterns to avoid shell expansion.
Multiple matches are listed before one default-No confirmation; `--yes` / `-y`
skips it. Removal still confirms a single match. Operations run in name order
and stop at the first failure without rolling back earlier operations.
`--keep-data` applies to every matched removal.

List and preview tables include Image and Created. New deployments save
`Deployment.created_at` as a UTC datetime; older deployments return None and
display —. Reuse and restart preserve the timestamp.

### Hugging Face cache defaults (0.3.4+)

`load_hf_dataset` and `load_hf_repository` use Hugging Face-managed disk caches
by default. JSONL and gzip JSONL use `hf_hub_download` and BONDI's original decoder;
other formats use `load_dataset(streaming=False)` and the HF prepared dataset cache.
Pass `streaming=True` in Python or `--streaming` to `bondi dataset load-hf` or
`load-hf-repository` to stream remotely instead. This can transfer data again on
each load. Cache locations follow `HF_HOME`, `HF_HUB_CACHE` and
`HF_DATASETS_CACHE`; BONDI does not manage its own cache.
Metadata resolution still contacts the Hub, so caching is not an offline guarantee.

AptMQL loaders (0.3.5+; check installed exports) use the fixed
`MongoDB/AptMQL-Bench` repository. `load_aptmql_dataset("beer_factory", connection=...)`
loads all related collections into a MongoDB database, Couchbase scope or PostgreSQL schema named
`beer_factory`. Single-dataset calls allow `database`, `scope` or `schema` overrides respectively.
`load_aptmql_repository(connection=...)` loads all datasets under their source names.
Couchbase requires `bucket` for either function. The CLI commands are
`bondi dataset load-aptmql beer_factory` and `bondi dataset load-aptmql-repository`.
Both accept `--revision` and standard destination/write options. Pin a commit for
reproducibility. BSON files are cached and decoded incrementally with PyMongo;
no mongorestore is needed. Dump indexes and collection metadata are ignored.
Repository writes are non-atomic. Partial errors include earlier acknowledged writes.

[Dataset guide](https://relaxed-constraints.github.io/bondi/datasets/)

### Database versions

BONDI 0.1.8 adds version selection: pass `version="8.0.16"` to
`deploy_mongodb` and `version="7.6.12"` to `deploy_couchbase`, with matching
`--version` CLI options. Check installed signatures/help for availability.
MongoDB and Couchbase versions use numeric `major.minor.patch` strings. PostgreSQL uses `major.minor`.
New deployments still default to MongoDB 8.0.16 and Couchbase 7.6.2; Couchbase
edition is selected separately. Docker checks image availability at startup.

For an installation supporting this feature:

```python
deploy_mongodb("example-mongo", version="8.0.16")
deploy_couchbase("example-cb", version="7.6.12", edition="enterprise")
```

Equivalent CLI options are `bondi deployment create mongodb --version 8.0.16` and
`bondi deployment create couchbase --version 7.6.12 --edition enterprise`. Version aliases
such as `latest`, partial versions and arbitrary image references are rejected.

Omitted version (`None`) preserves an existing deployment's saved image, including
legacy custom images. An explicit version must match the saved image exactly;
conflicts fail before Docker access. The selected version is stored in
`Deployment.image`, without a separate version field. Other saved settings must
still match, except MongoDB memory options described below. Use a new name and free ports for another version; this feature does
not upgrade, downgrade or migrate an existing database.

### MongoDB memory limits (0.1.10+)

Check the installed signature/help for `memory_limit_mb` and
`wiredtiger_cache_size_gb` before using them. For a new deployment:

```python
deploy_mongodb("mongo-limited", port=27019, memory_limit_mb=1024, wiredtiger_cache_size_gb=0.25)
```

CLI equivalents are `--memory-limit-mb 1024 --wiredtiger-cache-size-gb 0.25`.
Container limits are positive integer MiB; cache sizes are finite numbers from
0.25 to 10000 GiB despite MongoDB's GB spelling. Booleans are invalid.
An explicit cache must be smaller than an explicit container cap for new
deployments; leave additional workload-dependent headroom. These options do
not increase Docker Desktop VM memory or automatically tune the cache.

Omission means no explicit cap/automatic cache for new deployments and reuse
for existing ones. Differing explicit MongoDB memory values emit UserWarning
and are ignored: existing settings remain unchanged and the deployment starts.
Do not describe a successful deploy call as having applied requested new limits;
inspect the returned handle. Other conflicts still fail. Couchbase behavior is
unchanged. `None` never clears a limit.

Handles expose both values; status reports saved configuration, not live
measurements. Missing legacy fields are `None`. Manual Compose overrides remain
untouched and are not inferred or adopted into metadata, even when requested
values match them. Do not remove a user's database to change memory settings.
See the [memory guide](https://relaxed-constraints.github.io/bondi/deployment/#mongodb-memory-limits).

### Couchbase memory budgets (0.3.3+)

BONDI 0.1.6 adds
`deploy_couchbase(..., memory_limit_mb=16384)` and
`bondi deployment create couchbase --memory-limit-mb 16384` for a 16 GiB container.
Check the installed signature or CLI help before using this option; 0.1.5 does
not support it. Values are positive integer MiB; the default remains 4096.

Distinguish three limits when diagnosing quota failures: Docker VM memory,
the container limit, and Couchbase Data/Index Service and bucket quotas.
Increasing VM memory alone does not raise the container limit. This option does
not change service or bucket quotas; leave room for other services and overhead.
Python callers can set `data_memory_mb`, `index_memory_mb` and `bucket_memory_mb`
at creation. Data and Index default to 512 MiB each; the bucket defaults to Data
and consumes that allocation, rather than adding to it. Data plus Index must be
smaller than the container limit; the bucket must not exceed Data. New deployments
save resolved defaults. Omitted quotas reuse existing saved values, explicit
conflicts fail, and startup checks saved quotas without resizing. Legacy metadata
without quotas remains unspecified; explicit quota requests conflict with it.
The CLI exposes only the container limit. Consumer projects choose experiment
budgets and pass them to BONDI rather than implementing their own REST helpers.

The limit is persisted as `Deployment.memory_limit_mb`. Conflicting deploy
requests fail before Docker access; use `get_deployment(name).start()` or
`bondi deployment start NAME` to reuse saved settings. Older metadata is interpreted as
4096 MiB, while existing Compose overrides remain untouched. The attribute
reports saved configuration, not observed Docker memory.

For existing deployments, follow the matching checkout's `docs/deployment.md`
container-memory migration: stop, privately back up saved files, update both
metadata `memory_limit_mb` and Compose `services.couchbase.mem_limit`, then start
with the same project and volume. Reload Python handles afterward. Do not delete
or redeploy user data to resize a container. Use documentation matching the installed version.

## Queries, workloads and execution

Offline construction and persistence:

```python
from bondi.mongodb import MongoCollectionRef, MongoFindQuery
from bondi.workload import Workload, WorkloadEntry

business = MongoCollectionRef("demo", "business")
query = MongoFindQuery(business, {"city": "Sydney"}, limit=5)
workload = Workload([WorkloadEntry(query, pattern_id=0)])
workload.save("workload.jsonl")
restored = Workload.load("workload.jsonl")
```

In checkouts supporting `MongoCollectionRef.from_namespace(namespace)`, use it
when you already have a string such as `"demo.business"`. It splits at the first
dot, preserving additional dots in the collection name and all case/whitespace.
Non-string inputs raise `TypeError`; missing dots, empty names, and null characters
raise `ValueError`. This constructor was added after the 0.1.4 release; check the
installed API before using it in a pinned consumer project.

`MongoAggregateQuery` describes pipelines. `CouchbaseQuery` preserves SQL++
text and named/positional parameters. Workloads preserve order and optional integer
pattern IDs and contain one backend. MongoDB payload persistence preserves BSON
types. Fingerprints identify serialized representations, not semantic equivalence.
Do not mutate query objects while an executor is using them.

Given an existing, running deployment named `lesson` with demo data loaded:

```python
from bondi.deployment import get_deployment
from bondi.mongodb import MongoExecutor, summarize

deployment = get_deployment("lesson")
with MongoExecutor.from_connection(deployment.connection) as executor:
    result = executor.run(query, collect_results=True)
    results = executor.run_workload(restored)
    summary = summarize(executor.profile(query).raw)
print(result.documents)
print(summary.plan_stages)
```

For direct synchronous SDK operations, use `MongoExecutor.client` or
`CouchbaseExecutor.cluster`. First access opens a separate connection pool,
and the executor closes the handle.

Executors consume all rows; `collect_results=True` additionally retains them.
Use context managers for owned connections. `MongoExecutor` and
`CouchbaseExecutor` are synchronous; `AsyncMongoExecutor` and
`AsyncCouchbaseExecutor` support async applications. Workload concurrency belongs
to the executor. Consult the execution guide for deadlines and error continuation;
if continuing on errors, inspect each result's `error`.

`run` performs normal execution, `explain` requests a plan, and `profile`
requests execution diagnostics. In MongoDB, profiling uses explain executionStats;
it is not a normal replay timing or the server profiler collection. The backend's
offline `summarize` interprets raw diagnostics into `QuerySummary`. Unsupported
metrics stay `None`; client elapsed time and server execution time are different
measurements. Couchbase diagnostic availability depends on edition and response.
Keep warmups, repetitions and index-building outside measured replay in consumer
benchmark scripts; BONDI does not supply a complete benchmarking protocol.

## Schema, estimation and generation

`bondi.schema.Schema.from_documents(documents)` inspects Python dictionaries
without a database. Null and missing fields differ. Value retention is opt-in;
use `values="distinct"` when generation needs observed values.

`MongoSampleEstimator` uses MongoDB matching semantics. Its context manages its
temporary sample, not the source collection. Omitting `sample_size` evaluates
the full population; a sample estimates cardinality and selectivity before query
skip, limit or projection. Small samples can miss rare matches. Read the estimation
guide before choosing fresh versus persisted sampling.

`MongoWorkloadGenerator` takes a collection, a schema, `MongoGenerationConfig` and,
optionally, a prepared estimator. It does not manage the estimator's lifecycle.
`generate(num_patterns=..., instances_per_pattern=..., seed=...)` produces a
workload; `return_patterns=True` also returns patterns. Instances may repeat.
A seed reproduces generation given unchanged ordered inputs; it does not make
database sampling deterministic. Sample-based selectivity bounds are not
full-population guarantees.

Current generation is synchronous, single-collection MongoDB flat-find generation.
Do not assume aggregation generation or Couchbase or PostgreSQL generation/estimation exists.
Use the documentation map for detailed contracts and runnable notebooks.

## External MongoDB JSON (0.1.5+)

Use `from bondi.mongodb import loads_query_json` to decode external query JSON
with BSON dates/ObjectIds while preserving `$regex` operator documents. Explicit
`$regularExpression` wrappers decode to native Regex. Invalid input raises
ValueError; non-string input raises TypeError. This is data decoding, not query
validation. Find persistence writes version 2 with BSON-aware projections, reads
legacy version 1, and changes find fingerprints. Use the installed version's API.


## Find-to-aggregation conversion (0.1.7+)

`MongoFindQuery.to_aggregate()` creates an independent `MongoAggregateQuery`
without connecting to a server. It emits filtering, sorting, skipping, limiting,
then projection stages, omitting default/empty components. It supports ordinary
projection flags, top-level `$slice`, bounded `$elemMatch` conditions, and positional
`$` with a sole `{array: {"$elemMatch": condition}}` filter. Special projections may
expand into `$set` and computed `$project` expressions; element matching requires
MongoDB 5.0+. Unsupported constructs raise `ValueError`, including `$where`,
`$near`, `$nearSphere`, `$natural` sort, duplicate sort keys, computed find
projections, dotted special-projection paths and ambiguous positional bindings.
Consult the conversion section of `docs/find-query.md` for the exact condition
subset. Statistics on converted pipelines count the translated expressions.


## MongoDB query statistics (0.1.7+)

`bondi.mongodb.query_statistics(query, include_nested_pipelines=False)` accepts
find and aggregation queries. Find queries use `to_aggregate()` first. It returns
`MongoQueryStatistics` with versioned predicate/operator/stage totals, histograms,
and ordered `MongoStageStatistics` records with tuple paths. Only `$match` stages
contribute predicates. Stage operators are separate from below-stage operators;
implicit filter equality counts as `$eq`. Nested pipelines are excluded by default
from all counts, or selected recursively with the boolean flag. Unsupported selected
syntax raises a path-bearing `ValueError`; partial counts are not returned. Use
`docs/mongodb-query-statistics.md` for the complete definitions and supported syntax.


Query statistics additionally expose `expression_depth`, `filter_logical_depth`,
`filter_logical_fan_out` (query maxima and stage-local values), and query-wide
`nested_pipeline_depth`. Logical shape recognizes implicit conjunctions without
adding `$and` operators. `$expr` is opaque to filter shape; its operators contribute
expression depth. Recursive pipeline depth includes empty child pipelines and is
zero in outer-only scope. Existing definition-version-1 counts are unchanged.

## Schema snapshots (0.1.9+)

Schema persistence requires BONDI 0.1.9 or newer.
Save a schema with `schema.save("schema.json")`; restore with
`Schema.load("schema.json")`. Snapshots retain observations and support updates,
without database access. Global flat-field order is not preserved, and aware
datetimes restore fixed offsets rather than named timezone identities. See the
[schema guide](https://relaxed-constraints.github.io/bondi/schemas/#save-and-reuse-a-snapshot).

## Workload result callbacks (0.1.9+)

Workload callbacks require BONDI 0.1.9 or newer; check the installed signature
for `on_result` when working with older environments. MongoDB and Couchbase
`run_workload`, `explain_workload` and `profile_workload` accept `on_result(position, entry, result)`. Use the original
zero-based position to associate completion-order callbacks with queries.

Prefer this hook for incremental progress and summary persistence instead of
replacing workload scheduling with a consumer loop. Sync callbacks run serially
on the caller thread, preserving Yanex context; do not use async callbacks or
call/close the same executor inside one. Async executors accept ordinary or
awaitable callbacks on their loop. Each worker awaits callback completion before
starting another query. Keep synchronous callbacks short.

Callbacks see success, captured-error and timeout outcomes, including in-flight
results drained after fail-fast scheduling. Callback failures propagate after
worker cleanup and are not database errors. Pending callbacks are not guaranteed
after abort/cancellation. Treat arguments as read-only; results are shared with
the return list and remain retained in memory. Keep persistence policy in the
consumer project. See the [callback guide](https://relaxed-constraints.github.io/bondi/executor/#per-query-result-callbacks).


## Executor health checks (0.1.10+)

Check installed signatures for `health_check_timeout_seconds` before using it.
Both backend executors provide `ping(timeout_seconds=5)` (await on async).
It returns None on success; availability/probe failures raise
`bondi.execution.DatabaseUnavailableError`. Native authentication/configuration
errors remain distinguishable.

For long-query workloads use `timeout_seconds=600,
health_check_timeout_seconds=5, continue_on_error=True`. Enabling checks adds
one bounded probe per operation and stops scheduling on availability/access
failures despite continue_on_error. No separate fail-fast flag exists.
None disables preflight and preserves old behavior. A standalone ping does not
enable preflight. MongoDB serverSelectionTimeoutMS alone may be overridden by its
operation deadline; Couchbase probes must test Query service, not just KV.

In-flight entries drain and deliver callbacks; unstarted entries remain None.
This can take the remaining query deadline. Do not describe it as immediate
cancellation. Probe failures have status "error", not a query timeout, and retain
their original cause where available. Query syntax errors and execution timeouts
may continue. Authentication failures stop scheduling; configuration/API errors
propagate. Normal single-query mid-execution errors retain their native types.

Probe overhead is `health_check_elapsed_ms`, excluded from `elapsed_ms` and the
query deadline. A query prevented by preflight has elapsed_ms=0. Availability is
a point-in-time observation, not proof of process death or future query success.
Keep checkpoint/rerun decisions downstream; do not add retries or restart
containers automatically. See the
[health-check guide](https://relaxed-constraints.github.io/bondi/executor/#bounded-health-checks).

## Index lifecycle

`FieldIndex`, `MongoIndex`, `CouchbaseIndex`, `PostgresIndex` and `IndexSet` define reusable indexes.
The generic `bondi.create_indexes()` accepts an IndexSet plus MongoDB `database` or
Couchbase `bucket`/`scope` or PostgreSQL `schema`, and a connection configuration.
For PostgreSQL, `FieldIndex` creates a B-tree on the JSONB path. Match the indexed
expression in the query. For text extraction or numeric casts, use
`PostgresIndex.btree()`. For JSONB containment, use `PostgresIndex.gin()`.
Replacement protects primary, unique, exclusion and replica-identity indexes.
These examples use the BONDI 0.4.0 connection settings API.

`create_indexes(..., replace=True)` removes all secondary indexes on the collections
included in the set, including indexes created outside BONDI, then creates the new
set. An empty collection list clears secondary indexes; omitted collections are
untouched. MongoDB `_id_` and Couchbase primary indexes are preserved. This is
non-atomic and must not run alongside concurrent index administration.

`remove_index(..., collection=ref, index=definition)` returns whether removal was
confirmed. `remove_indexes(..., indexes=index_set, database=...)` returns confirmed
removed names by collection; Couchbase uses bucket/scope and PostgreSQL uses schema. Removal uses explicit or
generated names, not semantic equivalence. Missing names are skipped; protected
primary requests fail before any deletion. Empty lists remove nothing.

`IndexCreationError` reports `completed` creations, `removed` names and a failure
`phase`. `IndexRemovalError` reports completed removals. Both retain the native
cause and failed collection; neither rolls back. Use the index guide and API
reference in the matching checkout for exact fields and timeout semantics.


Generic `bondi.create_index`, `create_indexes`, `remove_index` and `remove_indexes`
dispatch from the connection type. Explicit backend functions are
`create_mongo_index[es]` / `remove_mongo_index[es]` in `bondi.mongodb` and
`create_couchbase_index[es]` / `remove_couchbase_index[es]` in `bondi.couchbase`, and
`create_postgres_index[es]` / `remove_postgres_index[es]` in `bondi.postgresql`.
There are no old-name backend aliases. Namespace arguments must match the backend.
