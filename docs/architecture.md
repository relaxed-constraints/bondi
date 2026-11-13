# Architecture and design

## Toolkit boundary

The toolkit supplies database interactions and reusable representations. Models,
index recommendation algorithms and experiment tracking remain in research projects.
Promote project code only when its contract is useful across projects and testable
independently. The toolkit has no dependency on mdbrtools or sibling repositories.

## Native queries, shared operations

MongoDB find/pipeline objects and Couchbase SQL++ objects preserve native query forms.
There is no intermediate query language or cross-backend translation.
MongoDB find queries can be explicitly converted to aggregation through
`MongoFindQuery.to_aggregate()` for supported syntax. `Query` is a small
structural protocol for validation, persistence and identity. A `Workload` groups
entries from one backend, retaining input order and optional integer pattern IDs.

## Execution and interpretation

Executors own or borrow backend connections. Async implementations perform I/O;
synchronous adapters use a dedicated background loop and are the teaching default.
Workload concurrency stays inside the executor rather than a separate runner class.
Queries are passed by reference and must not be mutated during operations.
Per-result workload callbacks are serialized per call. Async callbacks run on the
executor loop; synchronous facades dispatch ordinary callbacks onto the caller
thread. Callback failures abort and drain workers without becoming database errors.

`run`, `explain` and `profile` separate normal execution from diagnostics.
`ExecutionResult` stores observations and raw data. Offline `summarize` functions
interpret those data into a conservative `QuerySummary`; missing information remains
missing. Backend-specific evidence is retained rather than forced into shared totals.

Offline MongoDB `query_statistics()` describes query syntax independently of
execution diagnostics. It normalizes find queries through `to_aggregate()`, uses
versioned definitions, and rejects unsupported selected syntax rather than
returning partial counts.

Optional executor health checks use independent short deadlines and separate
probe timing. Enabled checks stop workload scheduling on availability/access
failures while draining in-flight entries and preserving result callbacks.
Database health is observed through native probes, without Docker dependencies.

Sustained `generate_load()` uses the same executor error and health policies.
A shared scheduler owns per-client selection streams and phase boundaries;
`LoadResult` wraps individual execution outcomes or unresolved drain expiry.
Retention is optional, callbacks provide backpressure, and experiments own metric
interpretation, repetition, persistence and hard process watchdogs.

## Schema, estimation and generation

`Schema` consumes Python dictionaries incrementally without database access. Retaining
values is opt-in. Estimators provide a separate cardinality contract; MongoDB sampling
uses database matching semantics and owns only its temporary sample collection.
The synchronous generator consumes a schema and optional prepared estimator. It does
not own connections or sampling lifecycle. Pattern constraints remain native and
project-specific rules can be supplied through callbacks.

## Persistence and change policy

Queries are mutable and validated at checkpoints. JSONL workloads persist concrete
native query envelopes and pattern IDs, not connections or execution results.
MongoDB filter/projection/pipeline payloads preserve BSON types; envelope metadata uses plain
JSON. Fingerprints describe serialized representations, not semantic equivalence.
Versioned schema snapshots persist the observation tree and typed retained scalars.
Loading rebuilds parent links and lookup indexes; global field encounter order is
not a persistence guarantee.
The API is still evolving; changes are explicit and tested rather than hidden behind
speculative compatibility layers.

## Dataset loading

`bondi.data` reads existing documents and writes them to native databases.
Source readers, conversion rules and writers remain separate. Consumers own data generation and benchmark-specific verification.
Single-source loaders use exact collection references. Hub repository loading
maps configurations directly to collection names. There are no manifests.
Loading is synchronous and non-atomic. Partial results report acknowledged writes.
