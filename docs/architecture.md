# Architecture and design

## Toolkit boundary

The toolkit supplies database interactions and reusable representations. Models,
index recommendation algorithms and experiment tracking remain in research projects.
Promote project code only when its contract is useful across projects and testable
independently. The toolkit has no dependency on mdbrtools or sibling repositories.

## Native queries, shared operations

MongoDB find/pipeline objects and Couchbase SQL++ objects preserve native query forms.
There is no intermediate query language or automatic translation. `Query` is a small
structural protocol for validation, persistence and identity. A `Workload` groups
entries from one backend, retaining input order and optional integer pattern IDs.

## Execution and interpretation

Executors own or borrow backend connections. Async implementations perform I/O;
synchronous adapters use a dedicated background loop and are the teaching default.
Workload concurrency stays inside the executor rather than a separate runner class.
Queries are passed by reference and must not be mutated during operations.

`run`, `explain` and `profile` separate normal execution from diagnostics.
`ExecutionResult` stores observations and raw data. Offline `summarize` functions
interpret those data into a conservative `QuerySummary`; missing information remains
missing. Backend-specific evidence is retained rather than forced into shared totals.

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
MongoDB filter/pipeline payloads preserve BSON types; envelope metadata uses plain
JSON. Fingerprints describe serialized representations, not semantic equivalence.
The API is still evolving; changes are explicit and tested rather than hidden behind
speculative compatibility layers.
