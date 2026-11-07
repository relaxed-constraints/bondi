# API and CLI

## Environment and deployment

In a consumer uv project, install with `uv add bondi`, or
`uv add 'bondi[couchbase]'` when executing Couchbase queries. Python 3.11+ is
required. Respect existing version pins. The CLI manages local deployments; query
execution, schema inspection, estimation and generation are Python APIs.

Use managed deployments with Docker and Compose v2 running on the same machine:

```sh
uv run bondi deploy mongodb --name lesson --port 27019
uv run bondi load-demo-data lesson
uv run bondi status lesson
uv run bondi stop lesson
uv run bondi start lesson
```

Choose an unused name and port; do not assume a student's existing deployment is
disposable. Deployments start empty. Demo loading upserts eight fictional businesses
and replaces matching demo IDs; it does not reset arbitrary data.
For Couchbase, use `bondi deploy couchbase` and
`bondi load-demo-data couchbase --create-primary-index` for demo SQL++ queries.
Do not create that index implicitly in an index experiment.

Inspect `uv run bondi --help` and subcommand help for installed CLI options.
`python -m bondi` is also supported. Python equivalents live in
`bondi.deployment`: `deploy_mongodb`, `deploy_couchbase`, `get_deployment`
and `list_deployments`. A deployment handle exposes connection details and
lifecycle methods; loading a handle does not start the database.

Closing an executor does not stop Docker. CLI `bondi remove NAME` deletes data
and configuration by default, with confirmation; `--keep-data` preserves them.
In contrast, Python `deployment.remove()` retains data unless
`delete_data=True`. Match cleanup to the user's intended data ownership.
Use the managed API/CLI rather than legacy repository Compose scripts.

[Deployment guide](https://relaxed-constraints.github.io/bondi/deployment/)

### Couchbase container memory

BONDI 0.1.6 adds
`deploy_couchbase(..., memory_limit_mb=16384)` and
`bondi deploy couchbase --memory-limit-mb 16384` for a 16 GiB container.
Check the installed signature or CLI help before using this option; 0.1.5 does
not support it. Values are positive integer MiB; the default remains 4096.

Distinguish three limits when diagnosing quota failures: Docker VM memory,
the container limit, and Couchbase Data/Index Service and bucket quotas.
Increasing VM memory alone does not raise the container limit. This option does
not change service or bucket quotas; leave room for other services and overhead.
Experiment-specific quotas belong in the consumer project.

The limit is persisted as `Deployment.memory_limit_mb`. Conflicting deploy
requests fail before Docker access; use `get_deployment(name).start()` or
`bondi start NAME` to reuse saved settings. Older metadata is interpreted as
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
with MongoExecutor.from_uri(deployment.uri) as executor:
    result = executor.run(query, collect_results=True)
    results = executor.run_workload(restored)
    summary = summarize(executor.profile(query).raw)
print(result.documents)
print(summary.plan_stages)
```

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

`MongoWorkloadGenerator` takes a target, a schema, `MongoGenerationConfig` and,
optionally, a prepared estimator. It does not manage the estimator's lifecycle.
`generate(num_patterns=..., instances_per_pattern=..., seed=...)` produces a
workload; `return_patterns=True` also returns patterns. Instances may repeat.
A seed reproduces generation given unchanged ordered inputs; it does not make
database sampling deterministic. Sample-based selectivity bounds are not
full-population guarantees.

Current generation is synchronous, single-collection MongoDB flat-find generation.
Do not assume aggregation generation or Couchbase generation/estimation exists.
Use the documentation map for detailed contracts and runnable notebooks.

## External MongoDB JSON (0.1.5+)

Use `from bondi.mongodb import loads_query_json` to decode external query JSON
with BSON dates/ObjectIds while preserving `$regex` operator documents. Explicit
`$regularExpression` wrappers decode to native Regex. Invalid input raises
ValueError; non-string input raises TypeError. This is data decoding, not query
validation. Find persistence writes version 2 with BSON-aware projections, reads
legacy version 1, and changes find fingerprints. Use the installed version's API.


## Find-to-aggregation conversion (after 0.1.6)

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
